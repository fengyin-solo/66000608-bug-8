<template>
  <div ref="chartEl" class="chart-container"></div>
  <div v-if="knownIssues.length === 0" class="chart-empty">
    暂无可绘制的函数数据（所有函数均缺少采样数据）
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { GasIssue } from '@/types'

const props = defineProps<{ issues: GasIssue[] }>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

// 图表只遍历“已知”函数；数据直接取自父组件传入的同一数组
const knownIssues = computed(() => props.issues.filter((g) => g.known))

function render() {
  if (!chart) return
  const list = knownIssues.value
  chart.setOption({
    title: { text: '各函数 Gas 消耗对比（当前 vs 优化后）', left: 'center' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params: any[]) {
        const idx = params[0]?.dataIndex ?? 0
        const item = list[idx]
        if (!item) return ''
        return [
          item.signature,
          `当前: ${item.currentGas}`,
          `优化后: ${item.optimizedGas}`,
          `节省: ${item.savingGas} (${item.savingPercent ?? 0}%)`,
        ].join('<br/>')
      },
    },
    legend: { top: 28, data: ['当前消耗', '优化后消耗'] },
    grid: { left: 60, right: 24, top: 70, bottom: 80 },
    xAxis: {
      type: 'category',
      data: list.map((g) => g.signature),
      axisLabel: { rotate: 25 },
    },
    yAxis: { type: 'value', name: 'Gas' },
    series: [
      {
        name: '当前消耗',
        type: 'bar',
        data: list.map((g) => g.currentGas),
        itemStyle: { color: '#8b5cf6' },
      },
      {
        name: '优化后消耗',
        type: 'bar',
        data: list.map((g) => g.optimizedGas),
        itemStyle: { color: '#10b981' },
      },
    ],
  })
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    render()
    window.addEventListener('resize', onResize)
  }
})

watch(knownIssues, render, { deep: true })

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.chart-container {
  height: 400px;
  background: white;
  border-radius: 12px;
  padding: 1rem;
  margin-bottom: 1rem;
}
.chart-empty {
  text-align: center;
  color: #9ca3af;
  padding: 2rem 0;
}
</style>
