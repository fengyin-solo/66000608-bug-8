<template>
  <div class="history">
    <h2>审计历史</h2>
    <div v-if="store.results.length === 0 && !loading" class="empty">暂无审计记录。</div>
    <div class="history-list">
      <div v-for="item in store.results" :key="item.id" class="history-card">
        <div class="history-main">
          <div class="history-file">{{ item.filename }}</div>
          <div class="history-sub">
            {{ item.gasSummary?.knownCount ?? 0 }} 个函数已估算 · {{ formatTime(item.timestamp) }}
          </div>
        </div>
        <div class="history-score" :class="item.score >= 70 ? 'high' : item.score >= 40 ? 'medium' : 'low'">{{ item.score }}分</div>
        <button class="btn-sm" @click="openDetail(item.id)">查看详情</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuditStore } from "@/store"

const store = useAuditStore()
const router = useRouter()
const loading = ref(true)

onMounted(async () => {
  await store.fetchHistory()
  loading.value = false
})

function formatTime(iso: string) {
  if (!iso) return ""
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

async function openDetail(id: string) {
  try {
    await store.fetchAudit(id)
    router.push("/gas")
  } catch {
    // 结果既不在服务端也不在本地缓存时静默忽略
  }
}
</script>

<style scoped>
.history { max-width: 800px; }
.empty { color: #9ca3af; padding: 1rem 0; }
.history-list { display: flex; flex-direction: column; gap: 1rem; }
.history-card { background: white; border-radius: 12px; padding: 1.25rem; display: flex; align-items: center; gap: 1rem; }
.history-main { flex: 1; }
.history-file { font-weight: 600; }
.history-sub { font-size: 0.75rem; color: #9ca3af; margin-top: 0.25rem; }
.history-score { padding: 0.25rem 0.75rem; border-radius: 8px; font-weight: 600; font-size: 0.875rem; }
.history-score.high { background: #d1fae5; color: #065f46; }
.history-score.medium { background: #fef3c7; color: #92400e; }
.history-score.low { background: #fee2e2; color: #991b1b; }
.btn-sm { background: #e5e7eb; border: none; padding: 0.25rem 0.75rem; border-radius: 6px; cursor: pointer; font-size: 0.875rem; }
</style>
