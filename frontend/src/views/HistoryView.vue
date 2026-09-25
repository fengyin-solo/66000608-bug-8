<template>
  <div class="history">
    <h2>审计历史</h2>
    <div v-if="history.length === 0" class="empty-state">暂无审计记录，请先在「合约审计」页面执行审计。</div>
    <div class="history-list">
      <div v-for="item in history" :key="item.id" class="history-card">
        <div class="history-file">{{ item.filename }}</div>
        <div class="history-score" :class="item.score >= 70 ? 'high' : item.score >= 40 ? 'medium' : 'low'">{{ item.score }}分</div>
        <div class="history-time">{{ formatTime(item.timestamp) }}</div>
        <button class="btn-sm" @click="viewDetail(item)">查看详情</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useRouter } from "vue-router"
import { storeToRefs } from "pinia"
import { useAuditStore, type AuditResult } from "@/store"

const router = useRouter()
const store = useAuditStore()
const { results } = storeToRefs(store)

const history = computed(() => results.value)

function formatTime(ts: string): string {
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts : d.toLocaleString()
}

function viewDetail(item: AuditResult) {
  store.setCurrentResult(item)
  router.push("/")
}
</script>

<style scoped>
.history { max-width: 800px; }
.empty-state { background: white; border-radius: 12px; padding: 3rem; text-align: center; color: #6b7280; }
.history-list { display: flex; flex-direction: column; gap: 1rem; }
.history-card { background: white; border-radius: 12px; padding: 1.25rem; display: flex; align-items: center; gap: 1rem; }
.history-file { flex: 1; font-weight: 600; }
.history-score { padding: 0.25rem 0.75rem; border-radius: 8px; font-weight: 600; font-size: 0.875rem; }
.history-score.high { background: #d1fae5; color: #065f46; }
.history-score.medium { background: #fef3c7; color: #92400e; }
.history-score.low { background: #fee2e2; color: #991b1b; }
.history-time { color: #6b7280; font-size: 0.875rem; }
.btn-sm { background: #e5e7eb; border: none; padding: 0.25rem 0.75rem; border-radius: 6px; cursor: pointer; font-size: 0.875rem; }
.btn-sm:hover { background: #d1d5db; }
</style>
