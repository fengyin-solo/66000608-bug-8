<template>
  <div class="audit">
    <h2>智能合约安全审计</h2>
    <div class="upload-section">
      <textarea v-model="contractCode" class="code-editor" placeholder="// 粘贴 Solidity 合约代码..."></textarea>
      <div class="toolbar">
        <input v-model="filename" placeholder="文件名.sol" class="filename-input" />
        <button @click="runAudit" class="btn-primary" :disabled="!contractCode.trim() || isAuditing">
          {{ isAuditing ? "审计中..." : "开始审计" }}
        </button>
        <button
          v-if="result"
          class="btn-secondary"
          @click="goGas"
        >在 Gas 结果页查看</button>
      </div>
      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
    </div>
    <div v-if="result" class="result-section">
      <div class="score-card" :class="scoreClass">
        <div class="score-label">安全评分</div>
        <div class="score-value">{{ result.score }}</div>
        <div class="score-grade">{{ scoreGrade }}</div>
      </div>
      <div class="vulnerabilities">
        <h3>发现漏洞 ({{ result.vulnerabilities.length }})</h3>
        <div v-for="v in result.vulnerabilities" :key="v.id ?? (v.type + v.line)" class="vuln-card" :class="v.severity">
          <div class="vuln-header">
            <span class="vuln-type">{{ v.type }}</span>
            <span class="vuln-severity">{{ v.severity }} · 第 {{ v.line }} 行</span>
          </div>
          <div class="vuln-desc">{{ v.description }}</div>
          <div class="vuln-suggest">建议: {{ v.suggestion }}</div>
        </div>
        <div v-if="result.vulnerabilities.length === 0" class="no-vuln">未发现已知模式的漏洞。</div>
      </div>
      <div class="gas-section">
        <h3>
          Gas 分析（{{ result.gasSummary.knownCount }}/{{ result.gasSummary.functionCount }} 个函数已估算，
          {{ result.gasSummary.unknownCount }} 个未知）
        </h3>
        <GasIssueList :issues="result.gasIssues" :code-text="result.code" @fixed="onFixed" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue"
import { useRouter } from "vue-router"
import { useAuditStore } from "@/store"
import GasIssueList from "@/components/GasIssueList.vue"

const store = useAuditStore()
const router = useRouter()

const contractCode = ref(`// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleBank {
    mapping(address => uint) public balances;

    function deposit() public payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw(uint amount) public {
        require(balances[msg.sender] >= amount);
        (bool success,) = msg.sender.call{value: amount}("");
        require(success);
        balances[msg.sender] -= amount;
    }
}`)
const filename = ref("SimpleBank.sol")
const isAuditing = ref(false)
const errorMsg = ref("")

const result = computed(() => store.currentResult)

const scoreClass = computed(() => {
  if (!result.value) return ""
  if (result.value.score >= 80) return "score-high"
  if (result.value.score >= 50) return "score-medium"
  return "score-low"
})

const scoreGrade = computed(() => {
  if (!result.value) return ""
  if (result.value.score >= 90) return "Excellent"
  if (result.value.score >= 70) return "Good"
  if (result.value.score >= 50) return "Fair"
  return "Poor"
})

async function runAudit() {
  isAuditing.value = true
  errorMsg.value = ""
  try {
    await store.uploadAndAudit(contractCode.value, filename.value.trim() || "untitled.sol")
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || "审计请求失败，请确认后端服务已启动。"
  } finally {
    isAuditing.value = false
  }
}

function goGas() {
  router.push("/gas")
}

// 自动修复生效后，编辑器同步为修复后的代码，列表已是新审计结果
function onFixed(fixedCode: string) {
  contractCode.value = fixedCode
}
</script>

<style scoped>
.audit { max-width: 1000px; }
.code-editor { width: 100%; height: 300px; font-family: "Fira Code", monospace; font-size: 0.875rem; padding: 1rem; border: 1px solid #d1d5db; border-radius: 8px; background: #1e1e1e; color: #d4d4d4; resize: vertical; }
.toolbar { display: flex; gap: 1rem; margin: 1rem 0; align-items: center; }
.filename-input { padding: 0.5rem 1rem; border: 1px solid #d1d5db; border-radius: 8px; flex: 1; }
.btn-primary { background: #8b5cf6; color: white; border: none; padding: 0.625rem 1.5rem; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #ede9fe; color: #6d28d9; border: none; padding: 0.625rem 1.25rem; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.error-msg { color: #dc2626; font-size: 0.875rem; }
.result-section { margin-top: 2rem; }
.score-card { border-radius: 16px; padding: 2rem; text-align: center; color: white; margin-bottom: 2rem; }
.score-high { background: linear-gradient(135deg, #10b981, #059669); }
.score-medium { background: linear-gradient(135deg, #f59e0b, #d97706); }
.score-low { background: linear-gradient(135deg, #ef4444, #dc2626); }
.score-label { font-size: 0.875rem; opacity: 0.9; margin-bottom: 0.5rem; }
.score-value { font-size: 4rem; font-weight: 800; }
.score-grade { font-size: 1.25rem; opacity: 0.9; }
.vulnerabilities h3, .gas-section h3 { margin-bottom: 1rem; font-size: 1.125rem; }
.vuln-card { background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; border-left: 4px solid; }
.vuln-card.critical { border-color: #dc2626; }
.vuln-card.high { border-color: #f59e0b; }
.vuln-card.medium { border-color: #3b82f6; }
.vuln-card.low { border-color: #6b7280; }
.vuln-header { display: flex; justify-content: space-between; margin-bottom: 0.75rem; }
.vuln-type { font-weight: 600; }
.vuln-severity { font-size: 0.75rem; color: #6b7280; }
.vuln-desc { color: #374151; margin-bottom: 0.5rem; }
.vuln-suggest { font-size: 0.875rem; color: #6b7280; }
.no-vuln { color: #059669; font-size: 0.875rem; }
.gas-section { margin-top: 2rem; }
</style>
