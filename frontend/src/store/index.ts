import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import axios from 'axios'
import type { ApiResponse } from '@/types'

export interface AuditResult {
  id: string
  filename: string
  score: number
  vulnerabilities: Vulnerability[]
  gasIssues: GasIssue[]
  timestamp: string
}

export interface Vulnerability {
  type: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  line: number
  description: string
  suggestion: string
}

export interface GasIssueDetail {
  id: string
  issue: string
  suggestion: string
  saving: number
}

export interface GasIssue {
  id: string
  functionName: string
  // null means the analyzer has no sampled data for this function ("未知")
  currentGas: number | null
  optimizedGas: number | null
  suggestion: string
  details: GasIssueDetail[]
}

const STORAGE_KEY = 'audit-store-v1'

function loadPersisted(): { results: AuditResult[]; currentResult: AuditResult | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return {
        results: Array.isArray(parsed.results) ? parsed.results : [],
        currentResult: parsed.currentResult ?? null,
      }
    }
  } catch {
    // corrupted cache — fall back to empty state
  }
  return { results: [], currentResult: null }
}

export const useAuditStore = defineStore('audit', () => {
  const persisted = loadPersisted()
  const results = ref<AuditResult[]>(persisted.results)
  const currentResult = ref<AuditResult | null>(persisted.currentResult)
  const patterns = ref<any[]>([])

  // Persist so a page refresh restores the exact same analysis data
  watch(
    [results, currentResult],
    () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ results: results.value, currentResult: currentResult.value })
      )
    },
    { deep: true }
  )

  async function uploadAndAudit(code: string, filename: string) {
    const res = await axios.post<ApiResponse<AuditResult>>('/api/audit', { code, filename })
    currentResult.value = res.data.data
    results.value.unshift(res.data.data)
    return res.data.data
  }

  function setCurrentResult(result: AuditResult | null) {
    currentResult.value = result
  }

  async function fetchPatterns() {
    const res = await axios.get<ApiResponse<any[]>>('/api/patterns')
    patterns.value = res.data.data
  }

  return { results, currentResult, patterns, uploadAndAudit, setCurrentResult, fetchPatterns }
})
