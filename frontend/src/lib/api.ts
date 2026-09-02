// 默认使用同源（后端直接托管前端时）；开发时可用 VITE_API_BASE 覆盖
const BASE = (import.meta.env.VITE_API_BASE as string) || ''

export interface Role {
  key: string
  name: string
  color: string
  stance: string
  duty: string
  group: string
  enabled: boolean
  order: number
  tools: string[]
  model?: string | null
  icon?: string
}

export interface CaseSummary {
  id: string
  title: string
  summary?: string
  brief?: { intake_done?: boolean } | string
  charts?: Record<string, string>
}

export interface Claim {
  id: string
  role_id: string
  agent: string
  round: number
  content: string
  cited: string[]
  t: number
}

export interface Contradiction {
  round?: number
  issue: string
  parties: string[]
}

export interface ReviewRequest {
  pending: boolean
  round: number
  question: string
}

export interface Verdict {
  truth_hypothesis?: string
  evidence_chain?: string[]
  doubts?: string[]
  recommendation?: string
  next_steps?: string[]
  disclaimer?: string
}

export interface TrialEvent {
  type: string
  [key: string]: unknown
}

export async function getRoles(): Promise<Role[]> {
  const r = await fetch(`${BASE}/api/roles`)
  const data = await r.json()
  return data.roles || data
}

export async function getCases(): Promise<CaseSummary[]> {
  const r = await fetch(`${BASE}/api/cases`)
  const data = await r.json()
  return data.cases || data
}

export async function getCase(id: string): Promise<unknown> {
  const r = await fetch(`${BASE}/api/cases/${id}`)
  return r.json()
}

export function apiBase(): string {
  return BASE
}
