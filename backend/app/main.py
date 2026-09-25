from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import re
import uuid
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = FastAPI(title="Smart Contract Security Auditor")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Vulnerability patterns
VULNERABILITY_PATTERNS = [
    {
        "type": "重入攻击 (Reentrancy)",
        "severity": "critical",
        "pattern": r"\.call\{[^}]*value:\s*[^}]*\}\([^)]*\)",
        "description": "使用低级call()或send()转移ETH存在重入攻击风险。攻击者可部署恶意合约在fallback中反复调用提款。",
        "suggestion": "使用Checks-Effects-Interactions模式，或引入ReentrancyGuard。推荐使用transfer()或call()并限制Gas。"
    },
    {
        "type": "整数溢出 (Integer Overflow/Underflow)",
        "severity": "high",
        "pattern": r"[+\-*/]\s*=|(&&|\|\|)\s*\w+\s*[<>=]",
        "description": "Solidity 0.7及以下版本，未使用SafeMath时可能发生整数溢出。",
        "suggestion": "使用SafeMath库或升级到Solidity 0.8+（内置溢出检查）。"
    },
    {
        "type": "未授权访问控制",
        "severity": "high",
        "pattern": r"function\s+\w+\s*\([^)]*\)\s*public\s*(payable)?\s*\{[^}]*(?:require|if)\s*\(",
        "description": "关键函数缺少访问控制检查，任何人都可以调用。",
        "suggestion": "添加onlyOwner或自定义访问控制修饰符。"
    },
    {
        "type": "selfdestruct使用",
        "severity": "medium",
        "pattern": r"selfdestruct|suicide",
        "description": "selfdestruct可强制将合约所有ETH发送到任意地址，可能被滥用。",
        "suggestion": "谨慎使用selfdestruct，确保有正当的业务需求。"
    },
    {
        "type": "tx.origin钓鱼",
        "severity": "high",
        "pattern": r"tx\.origin",
        "description": "使用tx.origin进行身份验证可能被钓鱼攻击，攻击者诱导用户触发交易。",
        "suggestion": "使用msg.sender代替tx.origin进行身份验证。"
    },
    {
        "type": "精确度损失",
        "severity": "medium",
        "pattern": r"/\s*\d+",
        "description": "除法运算可能导致精度损失，特别是在代币金额计算中。",
        "suggestion": "先乘后除，使用高精度计算或使用Babylonian方法。"
    },
]

# Gas optimization patterns: deterministic, code-driven analysis
GAS_PATTERNS = {
    "loop_storage": {
        "issue": "循环中读写storage变量",
        "suggestion": "将循环内反复访问的storage变量缓存到memory局部变量，循环结束后再写回storage",
    },
    "redundant_sstore": {
        "issue": "同一storage变量被重复写入",
        "suggestion": "合并对同一storage变量的多次写入，仅将最终状态写回storage",
    },
    "calldata_params": {
        "issue": "函数参数可使用calldata",
        "suggestion": "external函数的数组/字符串参数使用calldata代替memory，避免不必要的拷贝开销",
    },
    "short_circuit": {
        "issue": "逻辑运算可短路优化",
        "suggestion": "将开销低、更可能失败的条件放在&&/||前面，利用短路减少计算",
    },
}

# Deterministic gas cost model (approximate EVM costs)
BASE_TX_GAS = 21000
MIN_FUNCTION_GAS = 100  # sanity floor for optimized estimates
SLOAD_COST = 2100
SSTORE_COST = 5000
CALLDATA_PARAM_SAVING = 1000
SHORT_CIRCUIT_SAVING = 200
LOOP_ITERATIONS = 10  # estimated iteration count used for sampling

class AuditRequest(BaseModel):
    code: str
    filename: str

def detect_vulnerabilities(code: str) -> List[dict]:
    """Scan code for vulnerability patterns"""
    lines = code.split("\n")
    vulnerabilities = []
    
    for vp in VULNERABILITY_PATTERNS:
        matches = re.finditer(vp["pattern"], code, re.MULTILINE)
        for m in matches:
            line_num = code[:m.start()].count("\n") + 1
            # Find context
            context_start = max(0, line_num - 2)
            context_end = min(len(lines), line_num + 2)
            context = "\n".join(lines[context_start:context_end])
            
            vulnerabilities.append({
                "type": vp["type"],
                "severity": vp["severity"],
                "line": line_num,
                "description": vp["description"],
                "suggestion": vp["suggestion"],
                "code": context.strip()
            })
    
    return vulnerabilities

def _extract_brace_body(code: str, open_brace: int) -> str:
    """Return the content inside the braces starting at open_brace."""
    depth = 0
    for i in range(open_brace, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[open_brace + 1:i]
    return code[open_brace + 1:]

def extract_functions(code: str) -> List[dict]:
    """Extract function name, params, signature header and body."""
    functions = []
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\(([^)]*)\)([^{]*)\{", code):
        body = _extract_brace_body(code, m.end() - 1)
        functions.append({
            "name": m.group(1),
            "params": m.group(2),
            "header": m.group(3),
            "body": body,
        })
    return functions

def extract_state_variables(code: str) -> List[str]:
    """Extract contract-level state variable names (function bodies stripped)."""
    stripped = list(code)
    body_start_re = re.compile(
        r"\b(?:function\s+\w+|constructor|modifier\s+\w+|receive|fallback)\s*\([^)]*\)[^{]*\{"
    )
    for m in body_start_re.finditer(code):
        open_brace = m.end() - 1
        body = _extract_brace_body(code, open_brace)
        for i in range(open_brace, min(open_brace + len(body) + 2, len(stripped))):
            stripped[i] = " "
    contract_level = re.sub(r"\b(?:contract|library|interface|abstract\s+contract)\s+\w+[^{]*\{", " ", "".join(stripped))

    modifiers = {"public", "private", "internal", "constant", "immutable", "payable", "override"}
    names = []
    for stmt in contract_level.split(";"):
        stmt = stmt.strip()
        if not re.match(r"^(?:mapping\b|uint\d*\b|int\d*\b|address\b|bool\b|bytes\d*\b|string\b)", stmt):
            continue
        # Drop parenthesized type args (e.g. mapping(address => uint)) so the
        # variable name is the last identifier before any "= value" initializer.
        no_parens = re.sub(r"\([^()]*\)", "", stmt)
        no_parens = re.sub(r"\([^()]*\)", "", no_parens)
        m = re.search(r"(\w+)\s*(?:=[\s\S]*)?$", no_parens)
        if m and m.group(1) not in modifiers:
            names.append(m.group(1))
    return list(dict.fromkeys(names))

def _count_writes(body: str, var: str) -> int:
    """Count assignments (incl. compound) to a variable, excluding == comparisons."""
    pattern = rf"\b{re.escape(var)}\b(?:\s*\[[^\]]*\])*\s*(?:=(?!=)|\+=|-=|\*=|/=|\+\+|--)"
    return len(re.findall(pattern, body))

def _extract_loop_bodies(body: str) -> List[str]:
    loops = []
    for m in re.finditer(r"\b(?:for|while)\s*\([^)]*\)\s*\{", body):
        loops.append(_extract_brace_body(body, m.end() - 1))
    return loops

def compute_gas_issues(code: str) -> List[dict]:
    """Analyze gas consumption issues.

    Fully deterministic: the same source code always yields the same numbers.
    Functions with no detected optimization pattern get null gas values
    (rendered as "未知" by the frontend) instead of fabricated numbers.
    """
    state_vars = extract_state_variables(code)
    issues = []

    for index, fn in enumerate(extract_functions(code)):
        body = fn["body"]
        matched = []

        # 1. Storage variables accessed inside loops -> cache to memory
        loops = _extract_loop_bodies(body)
        loop_reads = loop_writes = 0
        for var in state_vars:
            for loop in loops:
                lw = _count_writes(loop, var)
                loop_writes += lw
                loop_reads += len(re.findall(rf"\b{re.escape(var)}\b", loop)) - lw
        if loop_reads + loop_writes:
            saving = (SLOAD_COST * loop_reads + SSTORE_COST * loop_writes) * (LOOP_ITERATIONS - 1)
            matched.append({"id": "loop_storage", **GAS_PATTERNS["loop_storage"], "saving": saving})

        # 2. Redundant writes to the same storage variable
        extra_writes = sum(
            writes - 1
            for var in state_vars
            for writes in [_count_writes(body, var)]
            if writes > 1
        )
        if extra_writes:
            saving = SSTORE_COST * extra_writes
            matched.append({"id": "redundant_sstore", **GAS_PATTERNS["redundant_sstore"], "saving": saving})

        # 3. external function params typed memory -> use calldata
        if "external" in fn["header"]:
            memory_params = len(re.findall(r"\bmemory\b", fn["params"]))
            if memory_params:
                saving = CALLDATA_PARAM_SAVING * memory_params
                matched.append({"id": "calldata_params", **GAS_PATTERNS["calldata_params"], "saving": saving})

        # 4. Boolean expressions that can benefit from short-circuit ordering
        bool_ops = len(re.findall(r"&&|\|\|", body))
        if bool_ops:
            saving = SHORT_CIRCUIT_SAVING * bool_ops
            matched.append({"id": "short_circuit", **GAS_PATTERNS["short_circuit"], "saving": saving})

        matched.sort(key=lambda m: m["saving"], reverse=True)
        entry = {
            "id": f"gas-{index}-{fn['name']}",
            "functionName": f"{fn['name']}()",
            "currentGas": None,
            "optimizedGas": None,
            "suggestion": "缺少采样数据，未检测到可优化的Gas模式",
            "details": [],
        }

        if matched:
            reads = writes = 0
            for var in state_vars:
                w = _count_writes(body, var)
                writes += w
                reads += len(re.findall(rf"\b{re.escape(var)}\b", body)) - w
            # Storage accesses inside loops are weighted by the estimated
            # iteration count, so estimates and savings stay coherent.
            current_gas = (
                BASE_TX_GAS
                + SLOAD_COST * (reads + loop_reads * (LOOP_ITERATIONS - 1))
                + SSTORE_COST * (writes + loop_writes * (LOOP_ITERATIONS - 1))
            )
            total_saving = sum(m["saving"] for m in matched)
            entry["currentGas"] = current_gas
            entry["optimizedGas"] = max(MIN_FUNCTION_GAS, current_gas - total_saving)
            entry["suggestion"] = matched[0]["suggestion"]
            entry["details"] = matched

        issues.append(entry)

    return issues

def compute_security_score(vulnerabilities: List[dict]) -> int:
    """Compute overall security score"""
    if not vulnerabilities:
        return 100
    severity_weights = {"critical": 25, "high": 15, "medium": 8, "low": 3}
    deduction = sum(severity_weights.get(v["severity"], 5) for v in vulnerabilities)
    return max(0, 100 - deduction)

@app.get("/")
async def root():
    return {"message": "Smart Contract Security Auditor", "version": "1.0.0"}

@app.get("/api/patterns")
async def list_patterns():
    return {"code": 0, "message": "success", "data": VULNERABILITY_PATTERNS}

@app.post("/api/audit")
async def audit_contract(request: AuditRequest):
    vulnerabilities = detect_vulnerabilities(request.code)
    gas_issues = compute_gas_issues(request.code)
    score = compute_security_score(vulnerabilities)
    
    result = {
        "id": str(uuid.uuid4()),
        "filename": request.filename,
        "score": score,
        "vulnerabilities": vulnerabilities,
        "gasIssues": gas_issues,
        "timestamp": datetime.now().isoformat()
    }
    
    return {"code": 0, "message": "success", "data": result}

@app.get("/api/history")
async def get_history():
    return {"code": 0, "message": "success", "data": []}

@app.post("/api/report/{audit_id}")
async def generate_report(audit_id: str):
    """Generate PDF report"""
    # Simplified report generation
    return {"code": 0, "message": "success", "data": {"url": f"/api/reports/{audit_id}.pdf"}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
