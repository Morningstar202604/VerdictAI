const BASE = (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8787'

export interface Role {
  id: string
  name: string
  color: string
  icon: string
  focus: string
}

export interface CaseSummary {
  id: string
  title: string
  brief: string
  scene_image?: string
  timeline_image?: string
  evidence_image?: string
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
  truth?: string
  motive?: string
  evidence_chain?: string[]
  doubts?: string[]
  recommendation?: string
}

export interface TrialEvent {
  type: string
  [key: string]: unknown
}

export async function getRoles(): Promise<Role[]> {
  const r = await fetch(`${BASE}/api/roles`)
  return r.json()
}

export async function getCases(): Promise<CaseSummary[]> {
  const r = await fetch(`${BASE}/api/cases`)
  return r.json()
}

export async function getCase(id: string): Promise<unknown> {
  const r = await fetch(`${BASE}/api/cases/${id}`)
  return r.json()
}

export function apiBase(): string {
  return BASE
}
