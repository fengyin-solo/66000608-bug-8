from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uuid
import re
from datetime import datetime

from .gas_analyzer import analyze_gas

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


class AuditRequest(BaseModel):
    code: str
    filename: str


class FixRequest(BaseModel):
    code: str
    filename: str
    fix: Dict[str, Any]


# 审计结果存储：同一代码（id 由内容用 uuid5 派生）命中同一份确定性数据
audit_store: "dict[str, dict]" = {}
# 历史按提交顺序记录（同一合约重复提交不产生重复条目）
audit_order: List[str] = []

AUDIT_NAMESPACE = uuid.UUID("6c6f736f-6c61-7564-6974-6e6f64650000")


def detect_vulnerabilities(code: str) -> List[dict]:
    """Scan code for vulnerability patterns"""
    lines = code.split("\n")
    vulnerabilities = []

    for vp in VULNERABILITY_PATTERNS:
        seen_positions = set()
        for m in re.finditer(vp["pattern"], code, re.MULTILINE):
            if m.start() in seen_positions:
                continue
            seen_positions.add(m.start())
            line_num = code[:m.start()].count("\n") + 1
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


def compute_security_score(vulnerabilities: List[dict]) -> int:
    """Compute overall security score"""
    if not vulnerabilities:
        return 100
    severity_weights = {"critical": 25, "high": 15, "medium": 8, "low": 3}
    deduction = sum(severity_weights.get(v["severity"], 5) for v in vulnerabilities)
    return max(0, 100 - deduction)


def build_audit_result(code: str, filename: str) -> dict:
    """对同一份代码构造确定性的审计结果（不含随机数）。"""
    vulnerabilities = detect_vulnerabilities(code)
    gas_issues, gas_summary = analyze_gas(code)
    score = compute_security_score(vulnerabilities)

    # uuid5：同一份代码永远得到同一个 id，刷新/重复审计都拿到同一组数据
    audit_id = str(uuid.uuid5(AUDIT_NAMESPACE, code))

    if audit_id in audit_store:
        stored = audit_store[audit_id]
        stored["filename"] = filename
        return stored

    result = {
        "id": audit_id,
        "filename": filename,
        "score": score,
        "vulnerabilities": vulnerabilities,
        # gasIssues 与 gasFunctions 指向同一份分析数据，图表和列表不可能对不上
        "gasIssues": gas_issues,
        "gasFunctions": gas_issues,
        "gasSummary": gas_summary,
        "code": code,
        "timestamp": datetime.now().isoformat(),
    }
    audit_store[audit_id] = result
    audit_order.append(audit_id)
    return result


@app.get("/")
async def root():
    return {"message": "Smart Contract Security Auditor", "version": "1.0.0"}


@app.get("/api/patterns")
async def list_patterns():
    return {"code": 0, "message": "success", "data": VULNERABILITY_PATTERNS}


@app.post("/api/audit")
async def audit_contract(request: AuditRequest):
    if not request.code or not request.code.strip():
        raise HTTPException(status_code=400, detail="合约代码不能为空")
    result = build_audit_result(request.code, request.filename)
    return {"code": 0, "message": "success", "data": result}


@app.get("/api/audit/{audit_id}")
async def get_audit(audit_id: str):
    result = audit_store.get(audit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="审计结果不存在或已过期")
    return {"code": 0, "message": "success", "data": result}


@app.get("/api/history")
async def get_history():
    data = [audit_store[i] for i in reversed(audit_order) if i in audit_store]
    return {"code": 0, "message": "success", "data": data}


@app.post("/api/gas/fix")
async def gas_fix(request: FixRequest):
    """应用某条 Gas 建议的自动修复。

    目前规则库只提供确定性的 memory -> calldata 关键字替换；
    无法安全自动改写（循环缓存、合并 SSTORE）的建议返回 400，
    引导用户参考 fixExample 手动修改，保证不会给出错误补丁。
    """
    fix = request.fix or {}
    code = request.code

    rule_id = fix.get("ruleId")
    if rule_id != "calldata_params":
        raise HTTPException(status_code=400,
                            detail="该建议暂不支持自动修复，请参考修复示例手动修改")

    start = fix.get("start")
    end = fix.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(code)):
        raise HTTPException(status_code=400, detail="修复位置无效")
    if code[start:end] != "memory":
        raise HTTPException(status_code=400, detail="目标位置不是 memory 关键字，无法替换")

    fixed_code = code[:start] + "calldata" + code[end:]
    result = build_audit_result(fixed_code, request.filename)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "fixedCode": fixed_code,
            "audit": result,
        },
    }


@app.post("/api/report/{audit_id}")
async def generate_report(audit_id: str):
    """Generate PDF report"""
    if audit_id not in audit_store:
        raise HTTPException(status_code=404, detail="审计结果不存在，无法生成报告")
    # Simplified report generation
    return {"code": 0, "message": "success", "data": {"url": f"/api/reports/{audit_id}.pdf"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
