import { useEffect, useRef, useState } from 'react'
import { api, type AutoMemoryResult } from '../services/api'

// Background learning usually finishes within a few seconds; poll with backoff and then stop.
export const POLL_DELAYS_MS = [700, 1200, 2000, 3000, 5000, 8000]

/** Polls the background LEARN -> RETAIN status of one incident until it is no longer pending. */
export function useLearningStatus(incidentId: string, initial: AutoMemoryResult, onSettled?: () => void) {
  const [state, setState] = useState(initial)
  const onSettledRef = useRef(onSettled)
  useEffect(() => {
    onSettledRef.current = onSettled
  }, [onSettled])

  const initialStatus = initial.status
  useEffect(() => {
    if (initialStatus !== 'pending') return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    const poll = (attempt: number) => {
      timer = setTimeout(async () => {
        let next: AutoMemoryResult | null = null
        try {
          next = await api.learning(incidentId)
        } catch {
          /* transient: retry on the next tick */
        }
        if (cancelled) return
        if (next) setState(next)
        if (next && next.status !== 'pending') onSettledRef.current?.()
        else if (attempt + 1 < POLL_DELAYS_MS.length) poll(attempt + 1)
      }, POLL_DELAYS_MS[attempt])
    }
    poll(0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [incidentId, initialStatus])

  return state
}
