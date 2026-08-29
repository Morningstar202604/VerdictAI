import { useCallback, useEffect, useRef, useState } from 'react'
import { type Claim, type Contradiction, type ReviewRequest, type Verdict } from './api'

export interface Status {
  phase: string
  round: number
  totalRounds: number
  speaker: string | null
  connection: 'idle' | 'connecting' | 'open' | 'closed'
  review: ReviewRequest | null
  error: string | null
}

export function useDebate(caseId: string | null) {
  const [claims, setClaims] = useState<Claim[]>([])
  const [contradictions, setContradictions] = useState<Contradiction[]>([])
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [status, setStatus] = useState<Status>({
    phase: 'idle',
    round: 0,
    totalRounds: 0,
    speaker: null,
    connection: 'idle',
    review: null,
    error: null,
  })
  const [running, setRunning] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const curKey = useRef<string | null>(null)
  const roundRef = useRef(0)

  const reset = useCallback(() => {
    setClaims([])
    setContradictions([])
    setVerdict(null)
    curKey.current = null
    roundRef.current = 0
    setStatus((s) => ({ ...s, phase: 'idle', round: 0, speaker: null, review: null, error: null }))
  }, [])

  const start = useCallback(() => {
    if (!caseId) return
    setRunning(true)
    reset()
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${proto}://${location.host}/ws/${caseId}`)
    wsRef.current = socket
    setStatus((s) => ({ ...s, connection: 'connecting', error: null }))

    socket.onopen = () => {
      setStatus((s) => ({ ...s, connection: 'open' }))
      socket.send(JSON.stringify({ type: 'start', case_id: caseId }))
    }

    socket.onmessage = (ev) => {
      const e = JSON.parse(ev.data)
      switch (e.kind) {
        case 'session_start':
          setStatus((s) => ({ ...s, phase: 'ready' }))
          break
        case 'round_start':
          roundRef.current = e.round
          setStatus((s) => ({ ...s, phase: 'debate', round: e.round, totalRounds: e.max_rounds || s.totalRounds }))
          break
        case 'agent_start': {
          const key = `${e.role}-${e.round ?? roundRef.current}`
          curKey.current = key
          setStatus((s) => ({ ...s, speaker: e.role, phase: 'debate' }))
          setClaims((prev) => [
            ...prev,
            { id: key, role_id: e.role, agent: e.name, round: e.round ?? roundRef.current, content: '', cited: [], t: Date.now() },
          ])
          break
        }
        case 'token':
          setClaims((prev) => prev.map((c) => (c.id === curKey.current ? { ...c, content: c.content + e.text } : c)))
          break
        case 'tool':
          setClaims((prev) =>
            prev.map((c) => (c.id === curKey.current ? { ...c, cited: [...c.cited, e.tool] } : c)),
          )
          break
        case 'agent_end':
          curKey.current = null
          setStatus((s) => ({ ...s, speaker: null }))
          break
        case 'round_end':
          break
        case 'critic_end':
          setContradictions((prev) => [...prev, ...(e.contradictions || [])])
          break
        case 'verdict':
          setVerdict(e.verdict)
          setStatus((s) => ({ ...s, phase: 'verdict' }))
          break
        case 'awaiting_human':
          setStatus((s) => ({
            ...s,
            phase: 'review',
            review: { pending: true, round: roundRef.current, question: '请人类法官确认 / 修正裁决' },
          }))
          break
        case 'human_done':
          setStatus((s) => ({ ...s, phase: 'debate', review: null }))
          break
        case 'done':
          setRunning(false)
          setStatus((s) => ({ ...s, phase: 'done', review: null }))
          break
        case 'error':
          setRunning(false)
          setStatus((s) => ({ ...s, error: e.message, connection: 'closed' }))
          break
      }
    }

    socket.onclose = () => setStatus((s) => ({ ...s, connection: 'closed' }))
    socket.onerror = () => setStatus((s) => ({ ...s, error: 'WebSocket 连接错误', connection: 'closed' }))
  }, [caseId, reset])

  const sendReview = useCallback((decision: string, note: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'human', text: note || decision }))
  }, [])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  return { claims, contradictions, verdict, status, running, reset, start, sendReview, disconnect }
}
