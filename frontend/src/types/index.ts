export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

export interface GasAutoFix {
  type: 'replace_keyword'
  keyword: string
  replacement: string
  start: number
  end: number
}

export interface GasSuggestion {
  ruleId:
    | 'calldata_params'
    | 'loop_storage_read'
    | 'cache_storage_read'
    | 'redundant_sstore'
  issue: string
  detail: string
  suggestion: string
  line: number
  saving: number
  fixExample: string
  autoFix: GasAutoFix | null
}

export interface GasIssue {
  id: string
  /** 简化名，如 f() */
  functionName: string
  /** 完整签名，如 f(uint[] memory a) */
  signature: string
  line: number
  visibility: string
  isView: boolean
  /** false 表示该函数缺少采样数据，Gas 数字应显示为“未知” */
  known: boolean
  currentGas: number | null
  optimizedGas: number | null
  savingGas: number | null
  savingPercent: number | null
  metrics: {
    sloads: number
    sstores: number
    loops: number
    events: number
    requires: number
    calls: number
  }
  suggestions: GasSuggestion[]
}

export interface GasSummary {
  functionCount: number
  knownCount: number
  unknownCount: number
  totalCurrentGas: number | null
  totalOptimizedGas: number | null
  totalSavingGas: number | null
  totalSavingPercent: number | null
}

export interface Vulnerability {
  id?: string
  type: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  line: number
  description: string
  suggestion: string
  code?: string
}

export interface AuditResult {
  id: string
  filename: string
  code?: string
  score: number
  vulnerabilities: Vulnerability[]
  gasIssues: GasIssue[]
  /** 与 gasIssues 同一份数据的别名 */
  gasFunctions?: GasIssue[]
  gasSummary: GasSummary
  timestamp: string
}

export interface FixResponse {
  fixedCode: string
  audit: AuditResult
}
