<template>
  <div class="gas-list">
    <div v-if="issues.length === 0" class="empty">该合约没有可分析的函数。</div>
    <div v-for="g in issues" :key="g.id" class="gas-card">
      <div class="gas-head">
        <span class="gas-fn">{{ g.signature }}</span>
        <span class="gas-line">第 {{ g.line }} 行 · {{ g.visibility }}{{ g.isView ? ' · view/pure' : '' }}</span>
      </div>
      <div class="gas-metrics">
        <span>SLOAD × {{ g.metrics.sloads }}</span>
        <span>SSTORE × {{ g.metrics.sstores }}</span>
        <span>循环 × {{ g.metrics.loops }}</span>
        <span>事件 × {{ g.metrics.events }}</span>
        <span>require × {{ g.metrics.requires }}</span>
        <span>调用 × {{ g.metrics.calls }}</span>
      </div>
      <div v-if="g.known" class="gas-info">
        当前: {{ g.currentGas?.toLocaleString() }} → 优化后: {{ g.optimizedGas?.toLocaleString() }}
        <span v-if="g.savingGas" class="gas-save-pct">
          （省 {{ g.savingGas.toLocaleString() }}，{{ g.savingPercent }}%）
        </span>
        <span v-else class="gas-save-pct">（暂无优化空间）</span>
      </div>
      <div v-else class="gas-unknown">
        消耗: 未知
        <span class="unknown-note">（缺少采样数据：接口/抽象函数或空函数体）</span>
      </div>
      <div
        v-for="s in g.suggestions"
        :key="g.id + ':' + s.ruleId + ':' + s.issue"
        class="gas-suggestion"
        @click="open(s, g)"
      >
        <span class="tip-badge" :class="s.ruleId">{{ tipLabel(s.ruleId) }}</span>
        <span class="tip-title">{{ s.issue }}</span>
        <span v-if="g.known && s.saving" class="tip-save">约省 {{ s.saving }} Gas ›</span>
        <span v-else class="tip-detail-link">详情 ›</span>
      </div>
    </div>

    <div v-if="active" class="modal-mask" @click.self="close">
      <div class="modal">
        <div class="modal-header">
          <span class="tip-badge" :class="active.tip.ruleId">{{ tipLabel(active.tip.ruleId) }}</span>
          <button class="modal-close" @click="close">×</button>
        </div>
        <h4 class="modal-title">{{ active.tip.issue }}</h4>
        <div class="modal-meta">
          <span>函数: {{ active.fn.signature }}</span>
          <span>位置: 第 {{ active.tip.line }} 行附近</span>
        </div>
        <p class="modal-detail">{{ active.tip.detail }}</p>
        <div class="modal-fix">
          <strong>修复方式：</strong>{{ active.tip.suggestion }}
        </div>
        <pre v-if="active.tip.fixExample" class="modal-example">{{ active.tip.fixExample }}</pre>
        <div v-if="active.fn.known" class="modal-gain">
          预计 Gas：{{ active.fn.currentGas?.toLocaleString() }}
          → {{ active.fn.optimizedGas?.toLocaleString() }}
          （节省 {{ active.tip.saving.toLocaleString() }}）
        </div>
        <div v-else class="modal-gain unknown">该函数缺少采样数据，消耗与节省量未知。</div>
        <div v-if="fixMsg" class="modal-fix-msg" :class="{ error: fixError }">{{ fixMsg }}</div>
        <div class="modal-actions">
          <button class="btn-copy" @click="copyTip">{{ copied ? '已复制' : '复制建议' }}</button>
          <button
            v-if="active.tip.autoFix && codeText"
            class="btn-apply"
            :disabled="fixing"
            @click="applyAutoFix"
          >{{ fixing ? '应用中…' : '一键应用修复' }}</button>
          <button class="btn-ok" @click="close">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { GasIssue, GasSuggestion } from '@/types'
import { useAuditStore } from '@/store'

const props = defineProps<{
  issues: GasIssue[]
  /** 提供原始合约代码时，弹窗支持“一键应用修复” */
  codeText?: string
}>()

const store = useAuditStore()
const active = ref<{ tip: GasSuggestion; fn: GasIssue } | null>(null)
const copied = ref(false)
const fixing = ref(false)
const fixMsg = ref('')
const fixError = ref(false)

function open(tip: GasSuggestion, fn: GasIssue) {
  copied.value = false
  fixMsg.value = ''
  fixError.value = false
  active.value = { tip, fn }
}

function close() {
  active.value = null
}

function tipLabel(ruleId: GasSuggestion['ruleId']) {
  switch (ruleId) {
    case 'calldata_params':
      return '方法参数'
    case 'loop_storage_read':
      return '循环缓存'
    case 'cache_storage_read':
      return '内存代替存储'
    case 'redundant_sstore':
      return '减少存储写入'
  }
}

async function copyTip() {
  if (!active.value) return
  try {
    await navigator.clipboard.writeText(
      `${active.value.tip.issue}\n${active.value.tip.detail}\n${active.value.tip.suggestion}\n\n示例：\n${active.value.tip.fixExample}`,
    )
    copied.value = true
  } catch {
    copied.value = false
  }
}

async function applyAutoFix() {
  if (!active.value?.tip.autoFix || !props.codeText) return
  fixing.value = true
  fixMsg.value = ''
  fixError.value = false
  try {
    const data = await store.applyFix(
      props.codeText,
      store.currentResult?.filename ?? 'contract.sol',
      {
        ruleId: active.value.tip.ruleId,
        functionId: active.value.fn.id,
        start: active.value.tip.autoFix.start,
        end: active.value.tip.autoFix.end,
      },
    )
    fixMsg.value = '修复已应用，分析结果已按新代码刷新。'
    emit('fixed', data.fixedCode)
  } catch (e: any) {
    fixError.value = true
    fixMsg.value = e?.response?.data?.detail || '自动修复失败，请参考修复示例手动修改。'
  } finally {
    fixing.value = false
  }
}

const emit = defineEmits<{ (e: 'fixed', fixedCode: string): void }>()
</script>

<style scoped>
.gas-list { display: flex; flex-direction: column; gap: 1rem; }
.empty { color: #9ca3af; padding: 1rem 0; }
.gas-card { background: white; border-radius: 12px; padding: 1.25rem; }
.gas-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; gap: 1rem; }
.gas-fn { font-weight: 600; color: #7c3aed; }
.gas-line { font-size: 0.75rem; color: #9ca3af; white-space: nowrap; }
.gas-metrics { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.gas-metrics span {
  font-size: 0.75rem; color: #6b7280; background: #f3f4f6;
  padding: 0.125rem 0.5rem; border-radius: 9999px;
}
.gas-info { color: #059669; font-size: 0.875rem; margin-bottom: 0.5rem; }
.gas-save-pct { color: #6b7280; }
.gas-unknown { color: #d97706; font-size: 0.875rem; margin-bottom: 0.5rem; }
.unknown-note { color: #9ca3af; font-size: 0.75rem; margin-left: 0.5rem; }
.gas-suggestion {
  display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.875rem; color: #374151;
  padding: 0.5rem 0.75rem; margin-top: 0.5rem;
  border: 1px solid #ede9fe; border-radius: 8px;
  background: #faf5ff; cursor: pointer; user-select: none;
}
.gas-suggestion:hover { border-color: #c4b5fd; }
.tip-title { flex: 1; }
.tip-save, .tip-detail-link { color: #7c3aed; font-size: 0.75rem; white-space: nowrap; }
.tip-badge {
  display: inline-block; font-size: 0.75rem; padding: 0.125rem 0.5rem;
  border-radius: 9999px; white-space: nowrap;
}
.tip-badge.calldata_params { background: #dbeafe; color: #1d4ed8; }
.tip-badge.loop_storage_read { background: #fef3c7; color: #92400e; }
.tip-badge.cache_storage_read { background: #e0e7ff; color: #3730a3; }
.tip-badge.redundant_sstore { background: #fee2e2; color: #b91c1c; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal { background: white; border-radius: 12px; width: 560px; max-width: calc(100vw - 2rem); max-height: 85vh; overflow-y: auto; padding: 1.5rem; }
.modal-header { display: flex; justify-content: space-between; align-items: center; }
.modal-close { border: none; background: none; font-size: 1.5rem; line-height: 1; cursor: pointer; color: #9ca3af; }
.modal-title { margin: 0.75rem 0 0.5rem; }
.modal-meta { display: flex; gap: 1rem; font-size: 0.75rem; color: #9ca3af; margin-bottom: 0.75rem; }
.modal-detail { color: #374151; font-size: 0.875rem; margin: 0 0 0.75rem; }
.modal-fix { font-size: 0.875rem; color: #374151; background: #f0fdf4; border-radius: 8px; padding: 0.75rem; }
.modal-example {
  background: #1e1e1e; color: #d4d4d4; font-size: 0.75rem;
  border-radius: 8px; padding: 0.75rem; margin: 0.75rem 0; overflow-x: auto;
  font-family: "Fira Code", monospace;
}
.modal-gain { margin-top: 0.75rem; font-size: 0.875rem; color: #059669; }
.modal-gain.unknown { color: #d97706; }
.modal-fix-msg { margin-top: 0.75rem; font-size: 0.8125rem; color: #059669; }
.modal-fix-msg.error { color: #dc2626; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.25rem; }
.btn-copy, .btn-apply, .btn-ok { border: none; border-radius: 8px; padding: 0.5rem 1rem; cursor: pointer; font-size: 0.875rem; }
.btn-copy { background: #f3f4f6; color: #374151; }
.btn-apply { background: #10b981; color: white; }
.btn-apply:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ok { background: #8b5cf6; color: white; }
</style>
