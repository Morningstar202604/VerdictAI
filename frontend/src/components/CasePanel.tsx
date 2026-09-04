import type { CaseSummary } from '../lib/api'
import { apiBase } from '../lib/api'

interface Props {
  cases: CaseSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  caseData: Record<string, unknown> | null
}

export default function CasePanel({ cases, selectedId, onSelect, caseData }: Props) {
  const c = cases.find((x) => x.id === selectedId)
  const charts = (caseData?.charts as Record<string, string>) || c?.charts || {}
  const chartEntries = Object.entries(charts).slice(0, 4)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-300">案件卷宗</h2>
        <span className="text-[10px] text-slate-500">CASE FILE</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {cases.map((x) => (
          <button
            key={x.id}
            onClick={() => onSelect(x.id)}
            className={`rounded-md border px-2.5 py-1 text-xs transition ${
              x.id === selectedId
                ? 'border-sky-500 bg-sky-500/10 text-sky-300'
                : 'border-edge text-slate-400 hover:border-slate-500'
            }`}
          >
            {x.title}
          </button>
        ))}
      </div>
      {c && (
        <div className="rounded-lg border border-edge bg-panel/60 p-3 space-y-2">
          <div className="text-sm font-medium text-slate-200">{c.title}</div>
          {c.summary && (
            <p className="text-xs leading-relaxed text-slate-400">{c.summary}</p>
          )}
          {chartEntries.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {chartEntries.map(([label, url]) => (
                <div key={label} className="space-y-1">
                  <div className="text-[10px] text-slate-500">{label}</div>
                  <img
                    src={`${apiBase()}${url}`}
                    alt={label}
                    className="w-full rounded border border-edge"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement
                      target.style.display = 'none'
                    }}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {caseData && (
        <div className="rounded-lg border border-edge bg-panel/60 p-3 text-[11px] leading-relaxed text-slate-400">
          <div className="mb-1 font-semibold text-slate-300">案情详情</div>
          <pre className="whitespace-pre-wrap font-sans max-h-64 overflow-y-auto">
            {JSON.stringify(caseData, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
