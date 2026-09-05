import { useEffect, useState } from 'react'
import { getRoles, getCases, getCase, type CaseSummary, type Role } from './lib/api'
import { useDebate } from './lib/useDebate'
import AgentGraph from './components/AgentGraph'
import CasePanel from './components/CasePanel'
import DebatePanel from './components/DebatePanel'
import VerdictPanel from './components/VerdictPanel'
import ErrorBoundary from './components/ErrorBoundary'

const PHASE_LABEL: Record<string, string> = {
  idle: '待命',
  ready: '就绪',
  debate: '辩论中',
  verdict: '裁决中',
  review: '待复核',
  done: '已完成',
}

export default function App() {
  const [roles, setRoles] = useState<Role[]>([])
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [caseData, setCaseData] = useState<Record<string, unknown> | null>(null)

  const { claims, contradictions, verdict, status, running, start, stop, sendReview } = useDebate(selectedId)

  useEffect(() => {
    getRoles().then(setRoles)
    getCases().then((c) => {
      setCases(c)
      if (c[0]) setSelectedId(c[0].id)
    })
  }, [])

  const onSelect = async (id: string) => {
    setSelectedId(id)
    const d = (await getCase(id)) as Record<string, unknown>
    setCaseData(d)
  }

  useEffect(() => {
    if (selectedId) onSelect(selectedId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  const phaseText = PHASE_LABEL[status.phase] || status.phase
  const connDot =
    status.connection === 'open'
      ? 'bg-emerald-400'
      : status.connection === 'connecting'
        ? 'bg-amber-400'
        : 'bg-slate-500'

  return (
    <ErrorBoundary>
    <div className="flex h-screen flex-col bg-ink font-sans text-slate-200">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-edge px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-sky-500/15 text-sky-300">
            {'\u26D3'}
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-wide text-slate-100">
              多智能体法律探案审判系统
            </h1>
            <p className="text-[10px] text-slate-400">
              Multi-Agent Legal Investigation & Trial · 7 专家辩论 · 纠错官 · 审判长收敛
            </p>
            <p className="text-[9px] text-slate-500">v{import.meta.env.PACKAGE_VERSION || '0.6.0'}</p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${connDot}`} />
            <span className="text-slate-300">{status.connection}</span>
          </div>
          <div className="text-slate-300">
            阶段 <span className="text-sky-300">{phaseText}</span>
            {status.totalRounds > 0 && (
              <span className="text-slate-400"> · 第 {status.round}/{status.totalRounds} 轮</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={start}
              disabled={!selectedId || running}
              className="rounded-md bg-sky-500 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {running ? '辩论进行中…' : '开始辩论'}
            </button>
            {running && (
              <button
                onClick={stop}
                className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20"
              >
                停止
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="grid flex-1 grid-cols-[300px_1fr_340px] gap-3 overflow-hidden p-3 md:grid-cols-[300px_1fr_340px] lg:grid-cols-[280px_1fr_320px]">
        <section className="space-y-3 overflow-y-auto rounded-xl border border-edge bg-panel/40 p-3">
          <AgentGraph roles={roles} activeId={status.speaker} phase={status.phase} />
          <CasePanel
            cases={cases}
            selectedId={selectedId}
            onSelect={(id) => setSelectedId(id)}
            caseData={caseData}
          />
        </section>

        <section className="rounded-xl border border-edge bg-panel/40 p-3">
          <DebatePanel claims={claims} roles={roles} />
        </section>

        <section className="overflow-y-auto rounded-xl border border-edge bg-panel/40 p-3">
          <VerdictPanel
            verdict={verdict}
            contradictions={contradictions}
            status={status}
            onReview={sendReview}
          />
          {status.error && (
            <div className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-[11px] text-rose-300">
              {status.error}
            </div>
          )}
        </section>
      </main>
    </div>
    </ErrorBoundary>
  )
}
