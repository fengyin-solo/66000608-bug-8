"""确定性的 Solidity Gas 静态分析。

同一份源码输入永远产生同一份结果：不使用随机数、不依赖时间，
Gas 数字由函数体中可计数的操作（SLOAD/SSTORE/循环/事件/参数等）按固定权重推导，
优化建议只在命中具体写法（循环内读 storage、重复写 storage、
external/public 的 string/bytes memory 参数）时生成。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 固定 Gas 权重（启发式估算，保证可复现）
# ---------------------------------------------------------------------------
W_BASE_EXTERNAL = 21_000    # public/external 调用基础成本
W_BASE_INTERNAL = 2_000     # internal/private 跳转
W_BASE_VIEW = 300           # view/pure 函数基础成本
W_BASE_CONSTRUCTOR = 41_000  # 部署构造（含一次初始 SSTORE）
W_PARAM = 30                # 每个入参的 ABI 解码成本
W_SLOAD = 2_100             # 一次冷 storage 读
W_SSTORE = 20_000           # 一次普通 storage 写
W_LOOP = 2_400              # 一层循环的固定开销
W_EVENT = 2_000             # 一次 emit
W_REQUIRE = 50              # 一次 require 校验
W_CALL = 2_500              # 一次内部/外部调用

# 每条优化建议对应的可节省 Gas（固定值）
SAVE_CALLDATA = 120         # string/bytes memory 参数改 calldata
SAVE_SLOAD = 2_100          # 每次可缓存的 SLOAD
SAVE_SSTORE_UPDATE = 2_900  # 首次写入后每次额外 SSTORE 更新

SAVING_CAP_RATIO = 0.4      # 节省上限不超过当前消耗的 40%

VISIBILITY_TOKENS = {"public", "external", "internal", "private"}
MUTABILITY_TOKENS = {"payable", "view", "pure", "virtual", "override"}
MODIFIER_KEYWORDS = {"constant", "immutable", "public", "private", "internal",
                     "external", "virtual", "override"}

FUNC_HEAD_RE = re.compile(
    r"\bfunction\s+[A-Za-z_]\w*|\bconstructor\b|\breceive\b|\bfallback\b"
)
CONTRACT_RE = re.compile(r"\b(?:abstract\s+)?(?:contract|library|interface)\s+\w+")
LOOP_RE = re.compile(r"\b(?:for|while)\b")


# ---------------------------------------------------------------------------
# 基础工具：在保留原长度/换行的前提下去掉注释与字符串字面量，
# 这样所有位置换算出来的行号与原始源码一致。
# ---------------------------------------------------------------------------
def strip_noise(code: str) -> str:
    out = list(code)
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and code[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (code[i] == "*" and i + 1 < n and code[i + 1] == "/"):
                if code[i] != "\n":
                    out[i] = " "
                i += 1
            if i + 1 < n:
                out[i] = out[i + 1] = " "
                i += 2
        elif c in ('"', "'"):
            quote = c
            out[i] = " "
            i += 1
            while i < n and code[i] != quote:
                if code[i] == "\\" and i + 1 < n:
                    if code[i] != "\n":
                        out[i] = " "
                    if code[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if code[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def _match_pair(s: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == open_ch:
            depth += 1
        elif s[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _line_of(code: str, idx: int) -> int:
    return code.count("\n", 0, idx) + 1


def _split_top_level(s: str, sep: str = ",") -> List[str]:
    parts: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    last = "".join(cur).strip()
    if last:
        parts.append(last)
    return parts


def _round10(v: float) -> int:
    return int(round(v / 10.0)) * 10


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
def _is_string_or_bytes(type_str: str) -> bool:
    t = type_str.strip()
    return t == "string" or t == "bytes" or t.startswith(("string ", "bytes "))


def _parse_params(param_text: str) -> List[dict]:
    params: List[dict] = []
    for raw in _split_top_level(param_text):
        tokens = raw.split()
        location: Optional[str] = None
        for loc in ("calldata", "memory", "storage"):
            if loc in tokens:
                location = loc
                tokens = [tk for tk in tokens if tk != loc]
        name: Optional[str] = None
        if tokens and re.fullmatch(r"[A-Za-z_]\w*", tokens[-1]):
            tail = tokens[-1]
            if tail not in VISIBILITY_TOKENS | MUTABILITY_TOKENS | {"calldata", "memory", "storage"}:
                name = tail
                tokens = tokens[:-1]
        type_str = " ".join(tokens) or (name or "unknown")
        params.append({
            "name": name,
            "type": type_str,
            "location": location,
            "isStringOrBytes": _is_string_or_bytes(type_str),
        })
    return params


# ---------------------------------------------------------------------------
# 函数与状态变量提取
# ---------------------------------------------------------------------------
def _extract_functions(src: str) -> List[dict]:
    funcs: List[dict] = []
    for m in FUNC_HEAD_RE.finditer(src):
        start = m.start()
        text = m.group(0)
        if "function" in text:
            name = text.split()[1]
            kind = "function"
        elif "constructor" in text:
            name, kind = "constructor", "constructor"
        elif "receive" in text:
            name, kind = "receive", "receive"
        else:
            name, kind = "fallback", "fallback"

        paren_open = src.find("(", start)
        if paren_open == -1 or paren_open > start + 200:
            continue
        paren_close = _match_pair(src, paren_open, "(", ")")
        if paren_close == -1:
            continue
        between = src[m.end():paren_open]
        if ";" in between or "{" in between:
            continue

        params = _parse_params(src[paren_open + 1:paren_close])

        body_start: Optional[int] = None
        body_end: Optional[int] = None
        header_end = len(src)
        i, depth = paren_close + 1, 0
        while i < len(src):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and ch == ";":
                header_end = i
                break
            elif depth == 0 and ch == "{":
                header_end = i
                body_start = i + 1
                body_end = _match_pair(src, i, "{", "}")
                break
            i += 1

        header = src[start:header_end]
        visibility: Optional[str] = None
        if kind in ("receive", "fallback"):
            visibility = "external"
        elif kind == "constructor":
            visibility = "internal"
        for tok in re.findall(r"[A-Za-z_]\w*", header[paren_close - start:]):
            if tok in VISIBILITY_TOKENS:
                visibility = tok
                break
        if visibility is None:
            visibility = "internal"  # Solidity 默认可见性

        is_view = bool(re.search(r"\b(?:view|pure)\b", header))
        is_payable = bool(re.search(r"\bpayable\b", header))
        sig = ",".join(
            (f"{p['type']} {p['location']} {p['name']}").replace("  ", " ").strip()
            if p["location"] else
            (f"{p['type']} {p['name']}").strip()
            for p in params
        )
        funcs.append({
            "index": len(funcs),
            "name": name,
            "kind": kind,
            "functionName": f"{name}()",
            "signature": f"{name}({sig})",
            "line": _line_of(src, start),
            "params": params,
            "visibility": visibility,
            "isView": is_view,
            "isPayable": is_payable,
            "body": src[body_start:body_end] if body_start is not None and body_end != -1 else None,
        })
    return funcs


def _top_level_statements(body: str) -> List[str]:
    statements: List[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0:
            stmt = body[start:i].strip()
            if stmt:
                statements.append(stmt)
            start = i + 1
    return statements


def _extract_state_vars(src: str) -> Dict[str, dict]:
    """收集合约体顶层的状态变量名（constant/immutable 不计运行期 storage）。"""
    state_vars: Dict[str, dict] = {}
    for cm in CONTRACT_RE.finditer(src):
        brace = src.find("{", cm.end())
        if brace == -1:
            continue
        close = _match_pair(src, brace, "{", "}")
        if close == -1:
            continue
        body = src[brace + 1:close]
        for stmt in _top_level_statements(body):
            first = re.match(r"[A-Za-z_]\w*", stmt)
            if first and first.group(0) in {"event", "error", "using", "modifier",
                                            "constructor", "function", "struct",
                                            "enum", "contract", "library", "interface"}:
                continue
            for decl in _split_top_level(stmt):
                eq = re.search(r"(?<![<>=!])=(?![=>])", decl)
                decl = (decl[:eq.start()] if eq else decl).strip()
                if decl.startswith("mapping("):
                    open_idx = decl.index("mapping(") + len("mapping")
                    mp = _match_pair(decl, open_idx, "(", ")")
                    tail = decl[mp + 1:] if mp != -1 else decl
                else:
                    tail = decl
                tokens = [t for t in re.findall(r"[A-Za-z_]\w*", tail)
                          if t not in MODIFIER_KEYWORDS
                          | {"memory", "calldata", "storage"}]
                if len(tokens) < 2 and not decl.startswith("mapping("):
                    continue
                if not tokens:
                    continue
                name = tokens[-1]
                words = set(re.findall(r"[A-Za-z_]\w*", decl))
                state_vars[name] = {
                    "constant": bool(words & {"constant", "immutable"}),
                }
    return state_vars


# ---------------------------------------------------------------------------
# 单个函数的 Gas 分析
# ---------------------------------------------------------------------------
def _loop_regions(body: str) -> List[Tuple[int, int]]:
    regions: List[Tuple[int, int]] = []
    for lm in LOOP_RE.finditer(body):
        cond_open = body.find("(", lm.start())
        if cond_open == -1:
            continue
        cond_close = _match_pair(body, cond_open, "(", ")")
        if cond_close == -1:
            continue
        j = cond_close + 1
        while j < len(body) and body[j] in " \t\r\n":
            j += 1
        if j < len(body) and body[j] == "{":
            end = _match_pair(body, j, "{", "}")
            regions.append((j + 1, end if end != -1 else len(body)))
        else:
            end = body.find(";", j)
            regions.append((j, end if end != -1 else len(body)))
    return regions


def _write_matches(body: str, var: str) -> List[re.Match]:
    return list(re.finditer(
        rf"\b{re.escape(var)}\b\s*(?P<idx>\[[^\]]*\]\s*)?(?P<op>[-+*/%])?=(?!=)",
        body,
    ))


def _read_spans(body: str, var: str) -> List[Tuple[int, int, str]]:
    """返回该变量的读取点 (起始, 结束, 标签)。

    映射/数组访问 var[k] 计一次读取，标签形如 var[]；
    其余裸引用（如复合写 var += 中伴随的读）计一次读取，标签为变量名。
    """
    spans: List[Tuple[int, int, str]] = []
    for m in re.finditer(rf"\b{re.escape(var)}\b\s*\[", body):
        close = body.find("]", m.start())
        if close != -1:
            spans.append((m.start(), close + 1, f"{var}[]"))
    return spans


def _access_metrics(body: str, var: str) -> dict:
    """统计一个状态变量在函数体内的读写情况。

    writes: 按“完整写入表达式”分组的次数（b[a] 与 b[c] 是不同槽位）；
    reads: 读取次数（含映射下标访问、复合写伴随读、其它裸引用）。
    """
    writes = _write_matches(body, var)
    write_spans = [(m.start(), m.end()) for m in writes]
    write_exprs: Dict[str, int] = {}
    compound_reads = 0
    for m in writes:
        idx = (m.group("idx") or "").strip()
        expr = f"{var}[{idx[1:-1].strip()}]" if idx else var
        write_exprs[expr] = write_exprs.get(expr, 0) + 1
        if m.group("op"):
            compound_reads += 1

    read_spans = _read_spans(body, var)
    index_reads = len([s for s in read_spans
                       if not any(a <= s[0] < b for a, b in write_spans)])
    # 裸引用 = 总标识符次数 − 写入处 − 映射/数组访问处
    all_refs = len(re.findall(rf"\b{re.escape(var)}\b", body))
    bare_reads = max(0, all_refs - len(writes) - len(read_spans))
    # 复合写（var += / var[k] +=）每处还伴随一次读取
    reads = index_reads + bare_reads + compound_reads

    return {
        "write_exprs": write_exprs,
        "reads": reads,
        "compound_reads": compound_reads,
        "is_mapping_read": bool(read_spans),
    }


def _param_memory_span(src: str, fn: dict, param: dict) -> Optional[Tuple[int, int]]:
    """在原始源码中定位该参数的 memory 关键字位置（供 autoFix 替换）。"""
    if param["location"] != "memory" or not param["name"]:
        return None
    m = re.search(
        rf"\b{re.escape(param['type'])}\s+memory\s+{re.escape(param['name'])}\b",
        src,
    )
    if not m:
        return None
    kw = re.search(r"\bmemory\b", m.group(0))
    if not kw:
        return None
    return m.start() + kw.start(), m.start() + kw.end()


def _analyze_function(fn: dict, state_vars: Dict[str, dict], src: str) -> dict:
    body = fn["body"]
    params = fn["params"]
    issue_id = f"{fn['name']}:{fn['index'] + 1}"

    # 没有函数体（abstract/interface）或空函数体：缺少采样数据
    has_statements = bool(body and re.search(r";", body))

    metrics = {"sloads": 0, "sstores": 0, "loops": 0,
               "events": 0, "requires": 0, "calls": 0}
    current_gas = optimized_gas = None
    saving_gas: Optional[int] = None
    saving_percent: Optional[float] = None
    shadowed: set = set()
    access: Dict[str, dict] = {}

    if has_statements:
        shadowed = set(re.findall(
            r"\b(?:uint\d*|int\d*|bytes\d*|address(?:\s+payable)?|bool|string)\s+"
            r"(?:memory\s+|calldata\s+|storage\s+)?([A-Za-z_]\w*)",
            body,
        ))
        # 每个状态变量 -> 访问统计；write_exprs 为“完整写入表达式 -> 次数”
        for var, meta in state_vars.items():
            if meta["constant"] or var in shadowed:
                continue
            info = _access_metrics(body, var)
            access[var] = info
            metrics["sloads"] += info["reads"]
            metrics["sstores"] += sum(info["write_exprs"].values())

        metrics["loops"] = len(_loop_regions(body))
        metrics["events"] = len(re.findall(r"\bemit\s+[A-Za-z_]\w*", body))
        metrics["requires"] = len(re.findall(r"\brequire\s*\(", body))
        call_names = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body))
        reserved = {
            "if", "for", "while", "switch", "catch", "return", "require",
            "assert", "revert", "function", "constructor",
        }
        metrics["calls"] = sum(1 for n in call_names if n not in reserved)

        if fn["kind"] == "constructor":
            current_raw = float(W_BASE_CONSTRUCTOR)
        elif fn["isView"]:
            current_raw = float(W_BASE_VIEW)
        elif fn["visibility"] in ("internal", "private"):
            current_raw = float(W_BASE_INTERNAL)
        else:
            current_raw = float(W_BASE_EXTERNAL)
        current_raw += len(params) * W_PARAM
        current_raw += metrics["sloads"] * W_SLOAD
        current_raw += metrics["sstores"] * W_SSTORE
        current_raw += metrics["loops"] * W_LOOP
        current_raw += metrics["events"] * W_EVENT
        current_raw += metrics["requires"] * W_REQUIRE
        current_raw += metrics["calls"] * W_CALL
        current_gas = _round10(max(current_raw, W_BASE_VIEW))

    # --- 优化建议（与具体写法对应，按规则+目标去重） -----------------------
    suggestions: List[dict] = []
    seen = set()

    def add_rule(rule_id: str, target: str, issue: str, detail: str,
                 suggestion: str, saving: int, fix_example: str,
                 auto_fix=None):
        key = (rule_id, target)
        if key in seen:
            return
        seen.add(key)
        suggestions.append({
            "ruleId": rule_id,
            "issue": issue,
            "detail": detail,
            "suggestion": suggestion,
            "line": fn["line"],
            "saving": saving if current_gas is not None else 0,
            "fixExample": fix_example,
            "autoFix": auto_fix,
        })

    # 1) external/public 的 string/bytes memory 参数 → calldata
    if fn["visibility"] in ("public", "external"):
        for p in params:
            if p["isStringOrBytes"] and p["location"] == "memory":
                target = p["type"]
                span = _param_memory_span(src, fn, p)
                auto_fix = None
                if span is not None:
                    auto_fix = {
                        "type": "replace_keyword",
                        "keyword": "memory",
                        "replacement": "calldata",
                        "start": span[0],
                        "end": span[1],
                    }
                add_rule(
                    "calldata_params", target,
                    f"外部函数参数应使用calldata: {target}",
                    "string/bytes 等动态类型参数使用 memory 时，ABI 编码数据会被完整拷贝进内存；"
                    "外部入口函数改用 calldata 可直接引用调用数据，省去这次拷贝。",
                    f"将外部函数的 {target} memory 参数改为 {target} calldata",
                    SAVE_CALLDATA,
                    f"function f({target} calldata data) external {{ ... }}",
                    auto_fix=auto_fix,
                )

    if body is not None and has_statements:
        # 2) 循环体内访问 storage 变量 → 缓存到 memory
        #    映射下标访问标签为 var[]；复合写 var += 在循环内也提示（每轮都 SLOAD）
        loop_targets: Dict[str, str] = {}
        for lo, hi in _loop_regions(body):
            region = body[lo:hi]
            for var, meta in state_vars.items():
                if meta["constant"] or var in shadowed:
                    continue
                info = _access_metrics(region, var)
                if info["reads"] > 0:
                    label = f"{var}[]" if info["is_mapping_read"] else var
                    loop_targets[label] = var
        for label in sorted(loop_targets):
            var = loop_targets[label]
            add_rule(
                "loop_storage_read", label,
                f"循环中重复读取storage变量: {label}",
                "循环每一轮都从存储槽读取状态变量，SLOAD 成本约 2100 gas/次。"
                "应在进入循环前一次性缓存到 memory，循环内使用局部变量。",
                "将循环内读取的状态变量缓存到 memory 局部变量后再使用",
                SAVE_SLOAD,
                f"uint256 cached = {var};\n"
                f"for (uint256 i = 0; i < n; i++) {{\n    total += cached;\n}}",
            )

        # 3) 同一状态变量在“循环体外”被读取多次 → cache_storage_read
        #    循环体内的读取只走 loop_storage_read，不计入此规则；
        #    循环条件（for (...)）位于循环体之外，照常统计。
        masked = list(body)
        for lo, hi in _loop_regions(body):
            for k in range(lo, hi):
                if masked[k] != "\n":
                    masked[k] = " "
        outside_body = "".join(masked)
        for var in sorted(access):
            outside_info = _access_metrics(outside_body, var)
            reads_out = outside_info["reads"]
            if reads_out >= 2:
                label = f"{var}[]" if outside_info["is_mapping_read"] else var
                add_rule(
                    "cache_storage_read", label,
                    f"重复读取storage变量可缓存: {label}",
                    "同一状态变量在函数中被读取多次，每次 SLOAD 约 2100 gas。"
                    "可先读取到 memory 局部变量复用，结束后一次性写回。",
                    "把多次读取的状态变量先缓存到 memory 局部变量",
                    SAVE_SLOAD * (reads_out - 1),
                    f"uint256 balance = {var};\nrequire(balance >= amount);\n{var} = balance;",
                )

        # 4) 同一存储槽（完整写入表达式相同）多次写入 → 合并冗余 SSTORE
        for var in sorted(access):
            for expr, count in sorted(access[var]["write_exprs"].items()):
                if count >= 2:
                    add_rule(
                        "redundant_sstore", expr,
                        f"同一存储槽被重复写入: {expr}",
                        "函数对同一个存储槽执行了多次 SSTORE，首次写入约 20000 gas、更新约 2900 gas。"
                        "先在 memory 中计算最终值，只写回一次可显著省气。",
                        "在 memory 中计算最终值后一次性写回存储",
                        SAVE_SSTORE_UPDATE * (count - 1),
                        f"uint256 newValue = balance + amount;\n{expr} = newValue;",
                    )

        total_saving = sum(s["saving"] for s in suggestions)
        total_saving = min(total_saving, int(current_gas * SAVING_CAP_RATIO))
        saving_gas = _round10(total_saving)
        optimized_gas = max(0, current_gas - saving_gas)
        saving_percent = round(saving_gas * 100.0 / current_gas, 1) if current_gas else 0.0

    return {
        "id": issue_id,
        "functionName": fn["functionName"],
        "signature": fn["signature"],
        "line": fn["line"],
        "visibility": fn["visibility"],
        "isView": fn["isView"],
        "known": current_gas is not None,
        "currentGas": current_gas,
        "optimizedGas": optimized_gas,
        "savingGas": saving_gas,
        "savingPercent": saving_percent,
        "metrics": metrics,
        "suggestions": suggestions,
    }


def analyze_gas(code: str) -> Tuple[List[dict], dict]:
    """返回 (每个函数的 Gas 分析, 汇总信息)。同一份代码结果恒定。"""
    cleaned = strip_noise(code)
    state_vars = _extract_state_vars(cleaned)
    issues = [_analyze_function(fn, state_vars, cleaned) for fn in _extract_functions(cleaned)]

    known = [i for i in issues if i["known"]]
    total_gas = sum(i["currentGas"] for i in known)
    total_optimized = sum(i["optimizedGas"] for i in known)
    total_saving = sum(i["savingGas"] for i in known)
    total_pct = round(total_saving * 100.0 / total_gas, 1) if total_gas else 0.0
    summary = {
        "functionCount": len(issues),
        "knownCount": len(known),
        "unknownCount": len(issues) - len(known),
        "totalCurrentGas": total_gas if known else None,
        "totalOptimizedGas": total_optimized if known else None,
        "totalSavingGas": total_saving if known else None,
        "totalSavingPercent": total_pct if known else None,
    }
    return issues, summary
