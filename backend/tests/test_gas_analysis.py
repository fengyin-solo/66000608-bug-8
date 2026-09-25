"""Gas 分析器与审计接口的回归测试。

运行：cd backend && .venv/bin/pytest -q
"""
import asyncio
import json

import httpx
import pytest

from app.gas_analyzer import analyze_gas
from app.main import app, build_audit_result

SAMPLE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleBank {
    mapping(address => uint) public balances;
    uint256 public total;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        total += msg.value;
        balances[msg.sender] += 1;
    }

    function withdraw(uint amount) external {
        require(balances[msg.sender] >= amount);
        uint cached = 0;
        for (uint i = 0; i < 10; i++) {
            cached += balances[msg.sender];
            total += 1;
        }
        balances[msg.sender] -= amount;
    }

    function batch(address to, bytes memory payload) external {
        // empty-ish: only comments
    }

    function balanceOf(address who) public view returns (uint) {
        return balances[who];
    }
}

interface ICounter {
    function tick(string memory name) external;
}
"""


def by_name(issues, sig):
    return next(i for i in issues if i["signature"] == sig)


def test_deterministic_same_input():
    r1 = json.dumps(analyze_gas(SAMPLE), sort_keys=True)
    r2 = json.dumps(analyze_gas(SAMPLE), sort_keys=True)
    assert r1 == r2


def test_build_audit_stable_id_and_data():
    a = build_audit_result(SAMPLE, "S.sol")
    b = build_audit_result(SAMPLE, "Renamed.sol")
    assert a["id"] == b["id"]  # id 由代码内容派生，与文件名无关
    assert a["gasIssues"] == b["gasIssues"]


def test_gasissues_and_gasfunctions_same_data():
    a = build_audit_result(SAMPLE, "S.sol")
    assert a["gasIssues"] is a["gasFunctions"]


def test_each_function_has_unique_id():
    issues, _ = analyze_gas(SAMPLE)
    ids = [i["id"] for i in issues]
    assert len(ids) == len(set(ids))
    sigs = [i["signature"] for i in issues]
    assert "deposit()" in sigs and "withdraw(uint amount)" in sigs


def test_unmeasured_functions_are_unknown():
    issues, summary = analyze_gas(SAMPLE)
    batch = by_name(issues, "batch(address to,bytes memory payload)")
    tick = by_name(issues, "tick(string memory name)")
    for item in (batch, tick):
        assert item["known"] is False
        assert item["currentGas"] is None
        assert item["optimizedGas"] is None
        assert item["savingGas"] is None
        assert item["savingPercent"] is None
    assert summary["unknownCount"] == 2
    assert summary["totalCurrentGas"] is not None


def test_loop_storage_read_detects_access_in_loop():
    issues, _ = analyze_gas(SAMPLE)
    wd = by_name(issues, "withdraw(uint amount)")
    loop_rules = [s for s in wd["suggestions"] if s["ruleId"] == "loop_storage_read"]
    # balances 映射访问、total 复合写在循环内都每轮触发 SLOAD，都应提示
    issues_hit = {s["issue"] for s in loop_rules}
    assert any("balances[]" in t for t in issues_hit)
    assert any("total" in t for t in issues_hit)


def test_cache_storage_read_rule():
    code = """
    contract C {
        mapping(address => uint) public b;
        function f() public view returns(uint) {
            return b[msg.sender] + b[msg.sender];
        }
    }
    """
    issues, _ = analyze_gas(code)
    cache = [s for s in issues[0]["suggestions"] if s["ruleId"] == "cache_storage_read"]
    assert len(cache) == 1
    assert "b[]" in cache[0]["issue"]
    assert cache[0]["saving"] == 2100  # 多读一次
    # 只读一次时不应提示
    code_once = code.replace("b[msg.sender] + b[msg.sender]", "b[msg.sender]")
    once, _ = analyze_gas(code_once)
    assert not any(s["ruleId"] == "cache_storage_read" for s in once[0]["suggestions"])


def test_calldata_rule_only_for_string_bytes_memory():
    issues, _ = analyze_gas(SAMPLE)
    tick = by_name(issues, "tick(string memory name)")
    cd = [s for s in tick["suggestions"] if s["ruleId"] == "calldata_params"]
    assert len(cd) == 1
    assert "string" in cd[0]["issue"]
    assert cd[0]["autoFix"] and cd[0]["autoFix"]["type"] == "replace_keyword"
    assert SAMPLE[cd[0]["autoFix"]["start"]:cd[0]["autoFix"]["end"]] == "memory"
    # uint value-type 参数不应触发
    wd = by_name(issues, "withdraw(uint amount)")
    assert not any(s["ruleId"] == "calldata_params" for s in wd["suggestions"])


def test_redundant_sstore_detected_once():
    issues, _ = analyze_gas(SAMPLE)
    dep = by_name(issues, "deposit()")
    rules = [s for s in dep["suggestions"] if s["ruleId"] == "redundant_sstore"]
    assert len(rules) == 1
    assert "balances" in rules[0]["issue"]


def test_suggestions_deduplicated_within_function():
    code = """
    contract C {
        uint public x;
        function f() external {
            x = 1; x = 2; x = 3;
        }
    }
    """
    issues, _ = analyze_gas(code)
    tips = [s for s in issues[0]["suggestions"] if s["ruleId"] == "redundant_sstore"]
    assert len(tips) == 1


def test_saving_consistency():
    issues, _ = analyze_gas(SAMPLE)
    for i in issues:
        if i["known"]:
            assert i["currentGas"] >= i["optimizedGas"]
            assert i["currentGas"] - i["optimizedGas"] == i["savingGas"]
            assert 0 <= (i["savingPercent"] or 0) <= 40


def test_empty_code_safe():
    issues, summary = analyze_gas("")
    assert issues == []
    assert summary["functionCount"] == 0
    assert summary["totalCurrentGas"] is None


def test_metrics_present_for_known():
    issues, _ = analyze_gas(SAMPLE)
    dep = by_name(issues, "deposit()")
    assert dep["metrics"]["sstores"] >= 2
    assert set(dep["metrics"]) == {"sloads", "sstores", "loops", "events", "requires", "calls"}


# ---------------- HTTP 层 ----------------

class ApiClient:
    """httpx 0.28 下直接走 ASGI transport，绕开 starlette TestClient 的版本不兼容。"""

    async def _request(self, method, path, payload=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, json=payload)

    def post(self, path, json=None):
        return asyncio.run(self._request("POST", path, json))

    def get(self, path):
        return asyncio.run(self._request("GET", path))


client = ApiClient()


def test_http_repeated_audit_identical():
    r1 = client.post("/api/audit", {"code": SAMPLE, "filename": "S.sol"})
    r2 = client.post("/api/audit", {"code": SAMPLE, "filename": "S.sol"})
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json()["data"], r2.json()["data"]
    assert d1["id"] == d2["id"]
    assert d1["gasIssues"] == d2["gasIssues"]
    assert d1["gasSummary"] == d2["gasSummary"]


def test_http_history_and_get_by_id():
    post = client.post("/api/audit", {"code": SAMPLE, "filename": "S.sol"}).json()["data"]
    hist = client.get("/api/history").json()["data"]
    assert any(h["id"] == post["id"] for h in hist)
    got = client.get(f"/api/audit/{post['id']}")
    assert got.status_code == 200
    assert got.json()["data"]["gasIssues"] == post["gasIssues"]
    assert client.get("/api/audit/missing").status_code == 404


def test_http_empty_code_rejected():
    assert client.post("/api/audit", {"code": "  ", "filename": "x.sol"}).status_code == 400


def test_http_gas_fix_calldata_applied():
    code = "interface I { function tick(string memory name) external; }"
    audit = client.post("/api/audit", {"code": code, "filename": "I.sol"}).json()["data"]
    tip = audit["gasIssues"][0]["suggestions"][0]
    assert tip["ruleId"] == "calldata_params"
    fix = client.post("/api/gas/fix", {
        "code": code,
        "filename": "I.sol",
        "fix": {"ruleId": "calldata_params",
                "functionId": audit["gasIssues"][0]["id"],
                "start": tip["autoFix"]["start"],
                "end": tip["autoFix"]["end"]},
    })
    assert fix.status_code == 200
    fixed = fix.json()["data"]["fixedCode"]
    assert "string calldata name" in fixed
    assert "string memory name" not in fixed


def test_http_gas_fix_unsupported_rule_returns_400():
    resp = client.post("/api/gas/fix", {
        "code": SAMPLE,
        "filename": "S.sol",
        "fix": {"ruleId": "loop_storage_read", "functionId": "x:1"},
    })
    assert resp.status_code == 400
    assert "手动修改" in resp.json()["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
