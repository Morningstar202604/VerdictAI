import type { Role } from '../lib/api'

interface Props {
  roles: Role[]
  activeId: string | null
  phase: string
}

const POS: Record<string, { x: number; y: number }> = {
  scene: { x: 80, y: 110 },
  forensic: { x: 80, y: 230 },
  evidence: { x: 80, y: 350 },
  psych: { x: 80, y: 470 },
  law: { x: 290, y: 150 },
  prosecutor: { x: 290, y: 290 },
  defense: { x: 290, y: 430 },
  judge: { x: 500, y: 290 },
}

export default function AgentGraph({ roles, activeId, phase }: Props) {
  return (
    <svg viewBox="0 0 580 580" className="w-full h-auto">
      <defs>
        <radialGradient id="core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#1b2a4a" />
          <stop offset="100%" stopColor="#0f141c" />
        </radialGradient>
      </defs>

      {roles.map((r) => {
        const p = POS[r.key]
        if (!p) return null
        const active = r.key === activeId
        const isSystem = r.key === 'judge' || r.key === 'critic'
        return (
          <g key={r.key}>
            <line
              x1={p.x + 40}
              y1={p.y}
              x2={500}
              y2={290}
              stroke={active ? r.color : '#1f2933'}
              strokeWidth={active ? 2 : 1}
              strokeDasharray="4 5"
              opacity={active ? 0.9 : 0.35}
            />
            {active && (
              <circle cx={p.x} cy={p.y} r={30} fill="none" stroke={r.color} strokeWidth={2} className="animate-pulseRing" />
            )}
            <circle
              cx={p.x}
              cy={p.y}
              r={24}
              fill={active ? r.color : '#0f141c'}
              stroke={r.color}
              strokeWidth={1.5}
              opacity={active ? 1 : 0.85}
            />
            <text x={p.x} y={p.y + 6} textAnchor="middle" fontSize="18">
              {r.icon || '◆'}
            </text>
            <text x={p.x + 34} y={p.y - 2} fill="#cbd5e1" fontSize="12" fontWeight={600}>
              {r.name}
            </text>
            <text x={p.x + 34} y={p.y + 13} fill="#64748b" fontSize="9">
              {isSystem ? '系统节点' : '调查专家'}
            </text>
          </g>
        )
      })}

      <circle cx={500} cy={290} r={46} fill="url(#core)" stroke="#3b82f6" strokeWidth={1.5} />
      <text x={500} y={285} textAnchor="middle" fontSize="20">
        {'\u2696'}
      </text>
      <text x={500} y={305} textAnchor="middle" fontSize="10" fill="#93c5fd">
        {phase === 'verdict' ? '已裁决' : phase === 'review' ? '待复核' : '收敛中'}
      </text>
    </svg>
  )
}
