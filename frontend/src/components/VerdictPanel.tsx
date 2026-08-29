import type { Contradiction, Verdict } from '../lib/api'
import type { Status } from '../lib/useDebate'

interface Props {
  verdict: Verdict | null
  contradictions: Contradiction[]
  status: Status
  onReview: (decision: string, note: string) => void
}

export default function VerdictPanel({ verdict, contradictions, status, onReview }: Props) {
  if (status.review?.pending) {
    return (
      <div className="space-y-3">
        <h2 className="text-sm font-semibold tracking-wide text-amber-300">审判长请求复核</h2>
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-200">
          {status.review.question}
        </div>
        <ReviewForm onReview={onReview} />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-300">裁决 / 矛盾分析</h2>
        <span className="text-[10px] text-slate-500">VERDICT</span>
      </div>

      {contradictions.length > 0 && (
        <div className="rounded-lg border border-edge bg-panel/60 p-3">
          <div className="mb-1.5 text-xs font-semibold text-rose-300">矛盾 / 纠错点</div>
          <ul className="space-y-1.5">
            {contradictions.map((c, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-slate-300">
                <span className="text-rose-400">⚠</span>{' '}
                {c.parties?.length ? `${c.parties.join(' ↔ ')}：` : ''}
                {c.issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {verdict ? (
        <div className="space-y-2.5 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3">
          <Field label="真相推定" value={verdict.truth} />
          <Field label="作案动机" value={verdict.motive} />
          {verdict.evidence_chain && verdict.evidence_chain.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold text-slate-400">证据链</div>
              <ol className="list-decimal space-y-1 pl-4 text-[12px] text-slate-200">
                {verdict.evidence_chain.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </div>
          )}
          {verdict.doubts && verdict.doubts.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold text-amber-300">存疑点</div>
              <ul className="list-disc space-y-1 pl-4 text-[12px] text-slate-300">
                {verdict.doubts.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          <Field label="处置建议" value={verdict.recommendation} />
        </div>
      ) : (
        <div className="flex h-32 items-center justify-center text-xs text-slate-600">
          辩论收敛后将生成裁决
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div>
      <div className="mb-0.5 text-[11px] font-semibold text-slate-400">{label}</div>
      <p className="text-[12px] leading-relaxed text-slate-200">{value}</p>
    </div>
  )
}

function ReviewForm({ onReview }: { onReview: (d: string, n: string) => void }) {
  const [note, setNote] = useState('')
  return (
    <div className="space-y-2">
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="复核意见（可选）"
        className="h-20 w-full resize-none rounded-md border border-edge bg-ink p-2 text-xs text-slate-200 outline-none focus:border-sky-500"
      />
      <div className="flex gap-2">
        <button
          onClick={() => onReview('accept', note)}
          className="flex-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20"
        >
          采纳并继续
        </button>
        <button
          onClick={() => onReview('reject', note)}
          className="flex-1 rounded-md border border-rose-500/40 bg-rose-500/10 py-1.5 text-xs text-rose-300 hover:bg-rose-500/20"
        >
          驳回重议
        </button>
      </div>
    </div>
  )
}
