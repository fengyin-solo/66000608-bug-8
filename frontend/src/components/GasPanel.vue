<template>
  <div class="gas-panel">
    <div class="summary-row" v-if="result">
      <div class="summary-card">
        <div class="summary-label">函数总数</div>
        <div class="summary-value">{{ result.gasSummary.functionCount }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">已估算 / 未知</div>
        <div class="summary-value">{{ result.gasSummary.knownCount }} / {{ result.gasSummary.unknownCount }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">总消耗（当前）</div>
        <div class="summary-value">{{ fmt(result.gasSummary.totalCurrentGas) }}</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">总节省</div>
        <div class="summary-value saving">
          {{ fmt(result.gasSummary.totalSavingGas) }}
          <span v-if="result.gasSummary.totalSavingPercent !== null" class="pct">
            （{{ result.gasSummary.totalSavingPercent }}%）
          </span>
        </div>
      </div>
    </div>
    <GasChart :issues="issues" />
    <h3>Gas 优化建议</h3>
    <GasIssueList :issues="issues" :code-text="result?.code" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AuditResult } from '@/types'
import GasChart from './GasChart.vue'
import GasIssueList from './GasIssueList.vue'

const props = defineProps<{ result: AuditResult | null }>()
// 图表与列表都遍历这同一个数组，保证两组数字必然一致
const issues = computed(() => props.result?.gasIssues ?? [])

function fmt(v: number | null) {
  return v === null ? '未知' : v.toLocaleString()
}
</script>

<style scoped>
.summary-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
.summary-card { background: white; border-radius: 12px; padding: 1rem 1.25rem; }
.summary-label { font-size: 0.75rem; color: #9ca3af; margin-bottom: 0.25rem; }
.summary-value { font-size: 1.5rem; font-weight: 700; color: #111827; }
.summary-value.saving { color: #059669; }
.pct { font-size: 0.875rem; font-weight: 400; }
h3 { margin: 1.5rem 0 1rem; font-size: 1.125rem; }
</style>
