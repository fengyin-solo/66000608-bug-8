<template>
  <div class="gas">
    <h2>Gas 消耗分析</h2>
    <div v-if="!currentResult" class="empty-state">
      暂无分析数据，请先在「合约审计」页面对合约执行审计。
    </div>
    <template v-else>
      <div class="gas-meta">合约: {{ currentResult.filename }}（与审计结果页数据一致）</div>
      <div ref="gasChart" class="chart-container"></div>
      <div class="gas-list">
        <h3>函数 Gas 明细</h3>
        <div v-for="g in gasIssues" :key="g.id" class="gas-row">
          <span class="gas-row-fn">{{ g.functionName }}</span>
          <template v-if="hasSample(g)">
            <span class="gas-row-nums">当前 {{ g.currentGas }} → 优化后 {{ g.optimizedGas }}</span>
            <span class="gas-row-pct">节省 {{ savingPercent(g) }}%</span>
          </template>
          <span v-else class="gas-row-unknown">未知（缺少采样数据）</span>
        </div>
      </div>
    </template>
    <div class="gas-tips">
      <h3>Gas优化技巧</h3>
      <ul>
        <li>使用 <code>calldata</code> 代替 <code>memory</code> 存储函数参数</li>
        <li>使用 <code>short-circuit</code> 逻辑减少不必要的计算</li>
        <li>避免在循环中读取存储变量，缓存到内存</li>
        <li>使用事件而非存储来记录历史数据</li>
        <li>合理使用 <code>unchecked</code> 块跳过溢出检查</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue"
import { storeToRefs } from "pinia"
import * as echarts from "echarts"
import { useAuditStore, type GasIssue } from "@/store"

const store = useAuditStore()
const { currentResult } = storeToRefs(store)

const gasChart = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const gasIssues = computed<GasIssue[]>(() => currentResult.value?.gasIssues ?? [])
// Only functions with sampled data can be charted; the rest show as 未知 in the list
const sampled = computed(() => gasIssues.value.filter(hasSample))

function hasSample(g: GasIssue): boolean {
  return g.currentGas != null && g.optimizedGas != null && g.currentGas > 0
}

function savingPercent(g: GasIssue): number {
  if (!hasSample(g)) return 0
  return Math.round((1 - (g.optimizedGas as number) / (g.currentGas as number)) * 100)
}

function renderChart() {
  if (!chart) return
  chart.setOption(
    {
      title: { text: "各函数Gas消耗对比", left: "center" },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      xAxis: { type: "category", data: sampled.value.map(g => g.functionName) },
      yAxis: { type: "value", name: "Gas" },
      series: [
        { name: "当前消耗", type: "bar", data: sampled.value.map(g => g.currentGas), itemStyle: { color: "#8b5cf6" } },
        { name: "优化后", type: "bar", data: sampled.value.map(g => g.optimizedGas), itemStyle: { color: "#10b981" } }
      ]
    },
    true
  )
}

onMounted(() => {
  if (gasChart.value) {
    chart = echarts.init(gasChart.value)
    renderChart()
  }
})

// Re-render when a new audit result arrives so chart and list stay in sync
watch(gasIssues, renderChart, { deep: true })

onUnmounted(() => { chart?.dispose() })
</script>

<style scoped>
.gas { max-width: 1000px; }
.empty-state { background: white; border-radius: 12px; padding: 3rem; text-align: center; color: #6b7280; margin-bottom: 2rem; }
.gas-meta { color: #6b7280; font-size: 0.875rem; margin-bottom: 0.75rem; }
.chart-container { height: 400px; background: white; border-radius: 12px; padding: 1rem; margin-bottom: 2rem; }
.gas-list { background: white; border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }
.gas-list h3 { margin-bottom: 1rem; }
.gas-row { display: flex; align-items: center; gap: 1rem; padding: 0.625rem 0; border-bottom: 1px solid #f3f4f6; font-size: 0.875rem; }
.gas-row:last-child { border-bottom: none; }
.gas-row-fn { font-weight: 600; color: #7c3aed; width: 160px; }
.gas-row-nums { color: #374151; flex: 1; }
.gas-row-pct { color: #059669; }
.gas-row-unknown { color: #9ca3af; flex: 1; }
.gas-tips { background: white; border-radius: 12px; padding: 1.5rem; }
.gas-tips h3 { margin-bottom: 1rem; }
.gas-tips ul { list-style: none; }
.gas-tips li { padding: 0.5rem 0; color: #374151; border-bottom: 1px solid #f3f4f6; }
.gas-tips li:last-child { border-bottom: none; }
.gas-tips code { background: #f3f4f6; padding: 0.125rem 0.375rem; border-radius: 4px; font-family: monospace; color: #7c3aed; }
</style>
