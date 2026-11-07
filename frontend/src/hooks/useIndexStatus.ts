import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, type IndexStatus } from '../lib/api'

/**
 * Live index status over Server-Sent Events, with a polling fallback.
 * Whenever a job finishes (or AI enrichment makes progress) the search caches are invalidated,
 * so new uploads appear without a manual refresh.
 */
export function useIndexStatus(): IndexStatus | null {
  const [status, setStatus] = useState<IndexStatus | null>(null)
  const qc = useQueryClient()
  const prev = useRef<IndexStatus | null>(null)

  useEffect(() => {
    let es: EventSource | null = null
    let poll: ReturnType<typeof setInterval> | null = null
    let closed = false

    const apply = (s: IndexStatus) => {
      const p = prev.current
      prev.current = s
      setStatus(s)
      const finished = p && p.state !== 'idle' && s.state === 'idle'
      const aiStep = p && s.state === 'enhancing' && s.done !== p.done && s.done % 5 === 0
      const countsChanged = p && JSON.stringify(p.counts) !== JSON.stringify(s.counts)
      if (finished || aiStep || countsChanged) {
        qc.invalidateQueries({ queryKey: ['search'] })
        qc.invalidateQueries({ queryKey: ['facets'] })
      }
    }

    const startPolling = () => {
      if (poll || closed) return
      poll = setInterval(() => api.status().then(apply).catch(() => {}), 3000)
    }

    api.status().then(apply).catch(() => {})
    if ('EventSource' in window) {
      es = new EventSource('/api/index/events')
      es.addEventListener('status', (e) => apply(JSON.parse((e as MessageEvent).data)))
      es.onerror = () => {
        es?.close()
        startPolling()
      }
    } else {
      startPolling()
    }
    return () => {
      closed = true
      es?.close()
      if (poll) clearInterval(poll)
    }
  }, [qc])

  return status
}
