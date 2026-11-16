import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Button, Spinner } from './ui'

const CHECK_EVERY_MS = 30 * 60 * 1000
const POLL_MS = 3000
const SLOW_AFTER_MS = 10 * 60 * 1000
const KEY = 'tl-updating-from'

type Phase = 'idle' | 'updating' | 'failed'

/**
 * Forced update: when GitHub has a newer version, the whole app is covered until the user clicks
 * "Update now". The server then updates itself and restarts; this screen waits for it to come
 * back on the new version and reloads the page.
 */
export function UpdateGate() {
  const q = useQuery({ queryKey: ['update'], queryFn: () => api.updateStatus(), refetchInterval: CHECK_EVERY_MS })
  const [phase, setPhase] = useState<Phase>(() => (readFrom() ? 'updating' : 'idle'))
  const [error, setError] = useState<string | null>(null)
  const [slow, setSlow] = useState(false)
  const startedAt = useRef<number>(0)
  const u = q.data
  const current = u?.current

  // While updating: the server goes away and comes back; reload once it runs a newer version
  useEffect(() => {
    if (phase !== 'updating') return
    if (!startedAt.current) startedAt.current = Date.now()
    const from = readFrom() ?? current ?? ''
    let stop = false
    const tick = async () => {
      try {
        const h = await fetch('/api/health', { cache: 'no-store' })
        if (h.ok) {
          const health = (await h.json()) as { version: string }
          if (health.version !== from) {
            clearFrom()
            window.location.reload()
            return
          }
          const st = await api.updateStatus()
          if (st.last_run?.state === 'failed') {
            clearFrom()
            setError(st.last_run.message || 'The update did not finish.')
            setPhase('failed')
            return
          }
        }
      } catch {
        /* server is restarting */
      }
      if (Date.now() - startedAt.current > SLOW_AFTER_MS) setSlow(true)
      if (!stop) window.setTimeout(tick, POLL_MS)
    }
    const t = window.setTimeout(tick, POLL_MS)
    return () => {
      stop = true
      window.clearTimeout(t)
    }
  }, [phase, current])

  const begin = async () => {
    setError(null)
    try {
      const r = await api.startUpdate()
      saveFrom(r.current)
      startedAt.current = Date.now()
      setSlow(false)
      setPhase('updating')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('failed')
    }
  }

  if (phase === 'idle' && !u?.update_required) return null
  const lastFailed = phase === 'idle' && u?.last_run?.state === 'failed' ? u.last_run.message : null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-title"
      data-testid="update-gate"
      className="fixed inset-0 z-[100] grid place-items-center bg-paper/95 p-4 backdrop-blur"
    >
      <div className="w-full max-w-[460px] rounded-[16px] border border-line bg-surface p-7 shadow-e2">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-full bg-ink-soft">
            <Download className="size-5 text-ink" />
          </span>
          <h2 id="update-title" className="text-[18px] font-semibold">
            {phase === 'updating' ? 'Updating TalentLens…' : 'A new version of TalentLens is ready'}
          </h2>
        </div>

        {phase === 'updating' ? (
          <div className="mt-4 text-[14px] leading-relaxed text-muted" data-testid="update-progress">
            <p className="flex items-center gap-2">
              <Spinner /> Downloading and installing. This usually takes 1–5 minutes.
            </p>
            <p className="mt-2">Keep this window open. It reloads by itself when the update is done.</p>
            {slow && (
              <p className="mt-2">
                This is taking longer than usual (a slow connection can do that). It will keep going in the background.
              </p>
            )}
          </div>
        ) : (
          <div className="mt-4 text-[14px] leading-relaxed text-muted">
            <p>
              Version <strong className="text-text">{u?.latest ?? 'new'}</strong> is available (you have {u?.current}).
              {' '}Please update to keep using TalentLens. Your resumes, settings and saved lists are kept.
            </p>
            {(error || lastFailed) && (
              <p className="mt-3 rounded-[10px] bg-danger-soft p-3 text-danger" data-testid="update-error">
                The last attempt didn't finish: {error || lastFailed}. TalentLens went back to the previous version, so
                nothing is lost. Try again; if it keeps failing, ask your administrator.
              </p>
            )}
            {u && !u.can_update ? (
              <p className="mt-4" data-testid="update-manual">
                This copy can't update itself because it wasn't installed from GitHub. Ask your administrator for the
                latest version.
              </p>
            ) : (
              <Button variant="primary" className="mt-5 w-full justify-center" onClick={begin} data-testid="update-now">
                Update now
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function readFrom(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}
function saveFrom(v: string) {
  try {
    sessionStorage.setItem(KEY, v)
  } catch {
    /* private mode: the poll still works without it */
  }
}
function clearFrom() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}
