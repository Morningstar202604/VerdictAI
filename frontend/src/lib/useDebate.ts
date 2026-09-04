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
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = 5
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
    reconnectAttempts.current = 0
  }, [])

  const reset = useCallback(() => {
    cleanup()
    setClaims([])
    setContradictions([])
    setVerdict(null)
    curKey.current = null
    roundRef.current = 0
    setStatus((s) => ({ ...s, phase: 'idle', round: 0, speaker: null, review: null, error: null }))
  }, [cleanup])

  const start = useCallback(() => {
    if (!caseId) return
    cleanup()
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
      reconnectAttempts.current = 0
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
          setStatus((s) => ({ ...s, phase: 'idle', error: e.message as string, connection: 'closed' }))
          break
      }
    }
    socket.onclose = (event) => {
      if (event.code === 4400 || event.code === 4401) {
        setStatus((s) => ({ ...s, connection: 'closed', error: '连接已断开' }))
        return
      }
      if (!running) return
      const attempts = reconnectAttempts.current + 1
      if (attempts <= maxReconnectAttempts) {
        reconnectAttempts.current = attempts
        const delay = Math.min(1000 * Math.pow(2, attempts - 1), 30000)
        setStatus((s) => ({ ...s, connection: 'connecting', error: `正在重连 (${attempts}/${maxReconnectAttempts})...` }))
        reconnectTimer.current = setTimeout(() => {
          const proto = location.protocol === 'https:' ? 'wss' : 'ws'
          const newSocket = new WebSocket(`${proto}://${location.host}/ws/${caseId}`)
          wsRef.current = newSocket
          newSocket.onopen = () => {
            reconnectAttempts.current = 0
            setStatus((s) => ({ ...s, connection: 'open', error: null }))
            newSocket.send(JSON.stringify({ type: 'start', case_id: caseId }))
          }
          newSocket.onmessage = socket.onmessage
          newSocket.onerror = () =>
            setStatus((s) => ({ ...s, error: 'WebSocket 连接错误', connection: 'closed' }))
          newSocket.onclose = socket.onclose
        }, delay)
      } else {
        setStatus((s) => ({ ...s, connection: 'closed', error: '连接中断，请刷新页面重试' }))
        setRunning(false)
      }
    }
    socket.onerror = () =>
      setStatus((s) => ({ ...s, error: 'WebSocket 连接错误', connection: 'closed' }))
  }, [caseId, reset, running, cleanup])

  const stop = useCallback(() => {
    cleanup()
    wsRef.current?.send(JSON.stringify({ type: 'stop' }))
  }, [cleanup])

  const sendReview = useCallback((decision: string, note: string) => {
    const text = note.trim() || (decision === 'accept' ? 'confirm' : decision)
    wsRef.current?.send(JSON.stringify({ type: 'human', text, subtype: 'final' }))
  }, [])

  const disconnect = useCallback(() => {
    cleanup()
    wsRef.current?.close()
    wsRef.current = null
  }, [cleanup])

  useEffect(() => {
    return () => {
      cleanup()
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [cleanup])

  return { claims, contradictions, verdict, status, running, reset, start, stop, sendReview, disconnect }
}
