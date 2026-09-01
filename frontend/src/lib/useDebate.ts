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
    // 启动新辩论前关闭旧连接
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
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
      let e: Record<string, unknown>
      try {
        e = JSON.parse(ev.data)
      } catch {
        return
      }
      switch (e.kind) {
        case 'session_start':
          setStatus((s) => ({ ...s, phase: 'ready' }))
          break
        case 'round_start':
          roundRef.current = e.round as number
          setStatus((s) => ({
            ...s,
            phase: 'debate',
            round: e.round as number,
            totalRounds: (e.max_rounds as number) || s.totalRounds,
          }))
          break
        case 'agent_start': {
          const key = `${e.role}-${(e.round as number) ?? roundRef.current}`
          curKey.current = key
          setStatus((s) => ({ ...s, speaker: e.role as string, phase: 'debate' }))
          setClaims((prev) => [
            ...prev,
            {
              id: key,
              role_id: e.role as string,
              agent: e.name as string,
              round: (e.round as number) ?? roundRef.current,
              content: '',
              cited: [],
              t: Date.now(),
            },
          ])
          break
        }
        case 'token':
          setClaims((prev) =>
            prev.map((c) => (c.id === curKey.current ? { ...c, content: c.content + (e.text as string) } : c)),
          )
          break
        case 'tool':
          setClaims((prev) =>
            prev.map((c) =>
              c.id === curKey.current ? { ...c, cited: [...c.cited, e.tool as string] } : c,
            ),
          )
          break
        case 'agent_end':
          curKey.current = null
          setStatus((s) => ({ ...s, speaker: null }))
          break
        case 'round_end':
          break
        case 'critic_end':
          setContradictions((prev) => [...prev, ...((e.contradictions as Contradiction[]) || [])])
          break
        case 'verdict':
          setVerdict(e.verdict as Verdict)
          setStatus((s) => ({ ...s, phase: 'verdict' }))
          break
        case 'awaiting_human':
          setStatus((s) => ({
            ...s,
            phase: 'review',
            review: {
              pending: true,
              round: roundRef.current,
              question: '请人类法官确认 / 修正裁决',
            },
          }))
          break
        case 'human_done':
          setStatus((s) => ({ ...s, phase: 'debate', review: null }))
          break
        case 'stopped':
          setRunning(false)
          setStatus((s) => ({ ...s, phase: 'idle', review: null }))
          break
        case 'done':
          setRunning(false)
          setStatus((s) => ({ ...s, phase: 'done', review: null }))
          break
        case 'error':
          setRunning(false)
          setStatus((s) => ({ ...s, error: e.message as string, connection: 'closed' }))
          break
      }
    }
    socket.onclose = () => setStatus((s) => ({ ...s, connection: 'closed' }))
    socket.onerror = () =>
      setStatus((s) => ({ ...s, error: 'WebSocket 连接错误', connection: 'closed' }))
  }, [caseId, reset])

  const stop = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'stop' }))
  }, [])

  const sendReview = useCallback((decision: string, note: string) => {
    // 后端 human_final_node 识别 "confirm"/"确认"/"ok"/"yes" 为采纳 AI 草案
    const text = note.trim() || (decision === 'accept' ? 'confirm' : decision)
    wsRef.current?.send(JSON.stringify({ type: 'human', text, subtype: 'final' }))
  }, [])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [])

  return { claims, contradictions, verdict, status, running, reset, start, stop, sendReview, disconnect }
}
