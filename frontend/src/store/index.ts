import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import type { ApiResponse, AuditResult, FixResponse } from '@/types'

const STORAGE_KEY = 'audit:history'

function loadCache(): AuditResult[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuditResult[]) : []
  } catch {
    return []
  }
}

/**
 * 审计结果的唯一事实来源（single source of truth）：
 * 分析页、Gas 结果页、历史页都从这里读同一份服务端数据，
 * localStorage 仅用于刷新后恢复，数据本身以后端返回为准。
 */
export const useAuditStore = defineStore('audit', () => {
  const results = ref<AuditResult[]>(loadCache())
  const currentResult = ref<AuditResult | null>(
    results.value.length ? results.value[0] : null,
  )
  const patterns = ref<any[]>([])

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(results.value))
    } catch {
      // localStorage 不可用时降级为纯内存
    }
  }

  function upsert(result: AuditResult) {
    const idx = results.value.findIndex((r) => r.id === result.id)
    if (idx >= 0) results.value.splice(idx, 1)
    results.value.unshift(result)
    currentResult.value = result
    persist()
  }

  async function uploadAndAudit(code: string, filename: string) {
    const res = await axios.post<ApiResponse<AuditResult>>('/api/audit', { code, filename })
    const result = res.data.data
    upsert(result)
    return result
  }

  async function fetchAudit(id: string) {
    const cached = results.value.find((r) => r.id === id)
    try {
      const res = await axios.get<ApiResponse<AuditResult>>(`/api/audit/${id}`)
      upsert(res.data.data)
      return res.data.data
    } catch {
      // 服务端已重启时回退到本地缓存，保证刷新后仍能看到同一份结论
      if (cached) {
        currentResult.value = cached
        return cached
      }
      throw new Error('审计结果不存在')
    }
  }

  async function fetchHistory() {
    try {
      const res = await axios.get<ApiResponse<AuditResult[]>>('/api/history')
      // 服务端历史与本地缓存按 id 合并，同 id 以服务端为准
      const merged = [...res.data.data]
      for (const local of results.value) {
        if (!merged.some((r) => r.id === local.id)) merged.push(local)
      }
      results.value = merged.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))
      persist()
    } catch {
      // 后端不可用时保留本地缓存
    }
    return results.value
  }

  async function fetchPatterns() {
    const res = await axios.get<ApiResponse<any[]>>('/api/patterns')
    patterns.value = res.data.data
  }

  /**
   * 应用某条建议的自动修复。服务端返回修复后的代码与新审计结果；
   * 服务端不支持自动修复时抛出自带的中文原因，由调用方展示。
   */
  async function applyFix(code: string, filename: string, fix: Record<string, unknown>) {
    const res = await axios.post<ApiResponse<FixResponse>>('/api/gas/fix', {
      code,
      filename,
      fix,
    })
    const data = res.data.data
    upsert(data.audit)
    return data
  }

  return {
    results,
    currentResult,
    patterns,
    uploadAndAudit,
    fetchAudit,
    fetchHistory,
    fetchPatterns,
    applyFix,
  }
})
