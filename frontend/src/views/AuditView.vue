<template>
  <div class="audit">
    <h2>智能合约安全审计</h2>
    <div class="upload-section">
      <textarea v-model="contractCode" class="code-editor" placeholder="// 粘贴 Solidity 合约代码..."></textarea>
      <div class="toolbar">
        <input v-model="filename" placeholder="文件名.sol" class="filename-input" />
        <button @click="runAudit" class="btn-primary" :disabled="!contractCode || isAuditing">
          {{ isAuditing ? "审计中..." : "开始审计" }}
        </button>
      </div>
      <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>
    </div>
    <div v-if="result" class="result-section">
      <div class="score-card" :class="scoreClass">
        <div class="score-label">安全评分</div>
        <div class="score-value">{{ result.score }}</div>
        <div class="score-grade">{{ scoreGrade }}</div>
      </div>
      <div class="vulnerabilities">
        <h3>发现漏洞 ({{ result.vulnerabilities.length }})</h3>
        <div v-for="(v, i) in result.vulnerabilities" :key="`${v.type}-${v.line}-${i}`" class="vuln-card" :class="v.severity">
          <div class="vuln-header">
            <span class="vuln-type">{{ v.type }}</span>
            <span class="vuln-severity">{{ v.severity }}</span>
          </div>
          <div class="vuln-desc">{{ v.description }}</div>
          <div class="vuln-suggest">建议: {{ v.suggestion }}</div>
        </div>
      </div>
      <div v-if="result.gasIssues.length > 0" class="gas-section">
        <h3>Gas优化建议</h3>
        <div
          v-for="g in result.gasIssues"
          :key="g.id"
          class="gas-card"
          :class="{ clickable: g.details.length > 0 }"
          @click="toggleGasDetail(g)"
        >
          <div class="gas-fn">
            {{ g.functionName }}
            <span v-if="g.details.length > 0" class="expand-hint">{{ expandedGasId === g.id ? "▲ 收起" : "▼ 修复提示" }}</span>
          </div>
          <div v-if="hasSample(g)" class="gas-info">
            当前: {{ g.currentGas }} → 优化后: {{ g.optimizedGas }} ({{ gasSavingPercent(g) }}%节省)
          </div>
          <div v-else class="gas-info gas-unknown">消耗未知（缺少采样数据）</div>
          <div class="gas-suggest">{{ g.suggestion }}</div>
          <div v-if="expandedGasId === g.id && g.details.length > 0" class="gas-details">
            <div v-for="d in g.details" :key="d.id" class="gas-detail-item">
              <div class="detail-issue">◆ {{ d.issue }}<span class="detail-saving">预计节省 {{ d.saving }} Gas</span></div>
              <div class="detail-fix">修复建议: {{ d.suggestion }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue"
import { storeToRefs } from "pinia"
import { useAuditStore, type GasIssue } from "@/store"

const store = useAuditStore()
const { currentResult } = storeToRefs(store)

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
const errorMessage = ref("")
const expandedGasId = ref<string | null>(null)

const result = computed(() => currentResult.value)

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

function hasSample(g: GasIssue): boolean {
  return g.currentGas != null && g.optimizedGas != null && g.currentGas > 0
}

function gasSavingPercent(g: GasIssue): number {
  if (!hasSample(g)) return 0
  return Math.round((1 - (g.optimizedGas as number) / (g.currentGas as number)) * 100)
}

function toggleGasDetail(g: GasIssue) {
  if (g.details.length === 0) return
  expandedGasId.value = expandedGasId.value === g.id ? null : g.id
}

async function runAudit() {
  isAuditing.value = true
  errorMessage.value = ""
  expandedGasId.value = null
  try {
    await store.uploadAndAudit(contractCode.value, filename.value)
  } catch (e) {
    errorMessage.value = "审计失败：无法连接服务端，请确认后端已启动后重试。"
  } finally {
    isAuditing.value = false
  }
}
</script>

<style scoped>
.audit { max-width: 1000px; }
.code-editor { width: 100%; height: 300px; font-family: "Fira Code", monospace; font-size: 0.875rem; padding: 1rem; border: 1px solid #d1d5db; border-radius: 8px; background: #1e1e1e; color: #d4d4d4; resize: vertical; }
.toolbar { display: flex; gap: 1rem; margin: 1rem 0; align-items: center; }
.filename-input { padding: 0.5rem 1rem; border: 1px solid #d1d5db; border-radius: 8px; flex: 1; }
.btn-primary { background: #8b5cf6; color: white; border: none; padding: 0.625rem 1.5rem; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.error-banner { background: #fee2e2; color: #991b1b; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1rem; }
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
.vuln-severity { padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; background: #fee2e2; color: #dc2626; }
.vuln-desc { color: #374151; margin-bottom: 0.5rem; }
.vuln-suggest { font-size: 0.875rem; color: #6b7280; }
.gas-card { background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }
.gas-card.clickable { cursor: pointer; }
.gas-card.clickable:hover { box-shadow: 0 2px 8px rgba(139, 92, 246, 0.15); }
.gas-fn { font-weight: 600; color: #7c3aed; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
.expand-hint { font-size: 0.75rem; color: #8b5cf6; font-weight: 400; }
.gas-info { color: #059669; font-size: 0.875rem; margin-bottom: 0.5rem; }
.gas-unknown { color: #9ca3af; }
.gas-suggest { font-size: 0.875rem; color: #6b7280; }
.gas-details { margin-top: 0.75rem; border-top: 1px dashed #e5e7eb; padding-top: 0.75rem; }
.gas-detail-item { background: #f9fafb; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 0.5rem; }
.gas-detail-item:last-child { margin-bottom: 0; }
.detail-issue { font-size: 0.875rem; color: #374151; font-weight: 500; display: flex; justify-content: space-between; }
.detail-saving { color: #059669; font-size: 0.75rem; }
.detail-fix { font-size: 0.8125rem; color: #6b7280; margin-top: 0.25rem; }
</style>
