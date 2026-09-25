<template>
  <div class="gas">
    <h2>Gas 消耗分析</h2>
    <div v-if="store.currentResult" class="result-meta">
      <span class="filename">{{ store.currentResult.filename }}</span>
      <span class="tip">图表与列表使用同一份分析数据</span>
    </div>

    <template v-if="store.currentResult">
      <GasPanel :result="store.currentResult" />
    </template>
    <div v-else class="no-data">
      <p>还没有分析结果。请先在“合约审计”页提交一份 Solidity 合约。</p>
      <router-link to="/" class="go-btn">去分析合约</router-link>
    </div>

    <div class="gas-tips">
      <h3>Gas 优化技巧</h3>
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
import { onMounted } from 'vue'
import { useAuditStore } from '@/store'
import GasPanel from '@/components/GasPanel.vue'

const store = useAuditStore()

// 页面刷新后 pinia 从 localStorage 恢复；能连到后端时再同步一次
onMounted(() => {
  if (store.results.length === 0) {
    store.fetchHistory()
  }
})
</script>

<style scoped>
.gas { max-width: 1000px; }
.result-meta { display: flex; align-items: baseline; gap: 1rem; margin-bottom: 1rem; }
.filename { font-weight: 600; color: #374151; }
.tip { font-size: 0.75rem; color: #9ca3af; }
.no-data {
  background: white; border-radius: 12px; padding: 3rem; text-align: center;
  color: #6b7280; margin-bottom: 2rem;
}
.go-btn {
  display: inline-block; margin-top: 1rem; background: #8b5cf6; color: white;
  padding: 0.5rem 1.25rem; border-radius: 8px; text-decoration: none;
}
.gas-tips { background: white; border-radius: 12px; padding: 1.5rem; margin-top: 2rem; }
.gas-tips h3 { margin-bottom: 1rem; }
.gas-tips ul { list-style: none; }
.gas-tips li { padding: 0.5rem 0; color: #374151; border-bottom: 1px solid #f3f4f6; }
.gas-tips li:last-child { border-bottom: none; }
.gas-tips code { background: #f3f4f6; padding: 0.125rem 0.375rem; border-radius: 4px; font-family: monospace; color: #7c3aed; }
</style>
