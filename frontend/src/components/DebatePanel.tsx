import { useEffect, useRef } from 'react'
import type { Claim, Role } from '../lib/api'

interface Props {
  claims: Claim[]
  roles: Role[]
}

export default function DebatePanel({ claims, roles }: Props) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [claims])

  const roleMap = Object.fromEntries(roles.map((r) => [r.id, r]))

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-300">辩论大厅</h2>
        <span className="text-[10px] text-slate-500">DEBATE FLOOR</span>
      </div>
      <div className="flex-1 space-y-2.5 overflow-y-auto pr-1">
        {claims.length === 0 && (
          <div className="flex h-full items-center justify-center text-xs text-slate-600">
            选择案件后点击「开始辩论」
          </div>
        )}
        {claims.map((c) => {
          const r = roleMap[c.role_id]
          const color = r?.color || '#64748b'
          const name = r?.name || c.agent || c.role_id
          const isSystem = c.role_id === 'judge' || c.role_id === 'critic'
          return (
            <div
              key={c.id}
              className="animate-fadeIn rounded-lg border border-edge bg-panel/70 p-3"
              style={{ borderLeft: `3px solid ${color}` }}
            >
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className="text-sm">{r?.icon || '•'}</span>
                <span className="font-semibold" style={{ color }}>
                  {name}
                </span>
                {isSystem && (
                  <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-300">
                    {c.role_id === 'judge' ? '审判长' : '证据审查官'}
                  </span>
                )}
                <span className="ml-auto text-[10px] text-slate-500">第 {c.round} 轮</span>
              </div>
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-200">
                {c.content}
                {c.cited?.length > 0 && (
                  <span className="ml-1 text-[11px] text-sky-400/80">
                    {' '}
                    〔引证 {c.cited.join('、')}〕
                  </span>
                )}
              </p>
            </div>
          )
        })}
        <div ref={endRef} />
      </div>
    </div>
  )
}
