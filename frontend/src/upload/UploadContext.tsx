import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, uploadWithProgress, type BulkResult } from '../lib/api'

export const RESUME_EXT = ['.pdf', '.docx', '.doc']
export const ACCEPT_EXT = [...RESUME_EXT, '.zip']
const MAX_FILE_MB = 20
const MAX_ZIP_MB = 300
const BATCH_FILES = 20
const BATCH_BYTES = 40 * 1024 * 1024

export type ItemStatus =
  | 'queued'
  | 'uploading'
  | 'reading' // saved, being read/indexed
  | 'ready'
  | 'duplicate'
  | 'rejected'
  | 'skipped'
  | 'unreadable'
  | 'failed' // network / server problem: can retry

export type UploadItem = {
  key: string
  label: string
  status: ItemStatus
  message?: string
  progress: number
  relPath?: string
  cvId?: number
  file?: File // kept so failed items can be retried
}

type Ctx = {
  items: UploadItem[]
  busy: boolean
  add: (files: File[]) => { accepted: number; ignored: number }
  retryFailed: () => void
  clear: () => void
}

const UploadCtx = createContext<Ctx | null>(null)

export const isAccepted = (name: string) => ACCEPT_EXT.some((e) => name.toLowerCase().endsWith(e))
const isZip = (name: string) => name.toLowerCase().endsWith('.zip')
let seq = 0

export function UploadProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [items, setItems] = useState<UploadItem[]>([])
  const itemsRef = useRef<UploadItem[]>([])
  useEffect(() => {
    itemsRef.current = items // current list for timers/async code without stale closures
  }, [items])
  const queue = useRef<UploadItem[]>([])
  const running = useRef(false)
  const polling = useRef<ReturnType<typeof setInterval> | null>(null)

  const patch = useCallback((keys: string[], change: Partial<UploadItem>) => {
    const set = new Set(keys)
    setItems((all) => all.map((it) => (set.has(it.key) ? { ...it, ...change } : it)))
  }, [])

  const startPolling = useCallback(() => {
    if (polling.current) return
    polling.current = setInterval(async () => {
      const waiting = itemsRef.current.filter((i) => i.status === 'reading' && i.relPath)
      if (!waiting.length) {
        clearInterval(polling.current!)
        polling.current = null
        qc.invalidateQueries({ queryKey: ['search'] })
        qc.invalidateQueries({ queryKey: ['facets'] })
        qc.invalidateQueries({ queryKey: ['recent'] })
        return
      }
      try {
        const st = await api.filesStatus(waiting.slice(0, 150).map((w) => w.relPath!))
        setItems((all) =>
          all.map((it) => {
            const s = it.relPath ? st[it.relPath] : undefined
            if (it.status !== 'reading' || !s || s.state === 'reading') return it
            return s.state === 'ready'
              ? { ...it, status: 'ready', cvId: s.id, message: 'Ready to search' }
              : { ...it, status: 'unreadable', cvId: s.id, message: "Saved, but the text couldn't be read" }
          }),
        )
      } catch {
        /* try again next tick */
      }
    }, 1500)
  }, [qc])

  const run = useCallback(async () => {
    if (running.current) return
    running.current = true
    try {
      while (queue.current.length) {
        // take a batch: up to 20 files / 40 MB, or a single ZIP
        const batch: UploadItem[] = []
        let bytes = 0
        while (queue.current.length) {
          const next = queue.current[0]!
          const size = next.file?.size ?? 0
          if (batch.length && (isZip(next.label) || batch.length >= BATCH_FILES || bytes + size > BATCH_BYTES)) break
          batch.push(queue.current.shift()!)
          bytes += size
          if (isZip(next.label)) break
        }
        const keys = batch.map((b) => b.key)
        patch(keys, { status: 'uploading', progress: 0 })
        try {
          const res = await uploadWithProgress(
            batch.map((b) => b.file!),
            (f) => patch(keys, { progress: f }),
          )
          applyResults(batch, res.results)
        } catch (e) {
          patch(keys, { status: 'failed', message: (e as Error).message, progress: 0 })
        }
      }
    } finally {
      running.current = false
      qc.invalidateQueries({ queryKey: ['search'] })
    }

    function applyResults(batch: UploadItem[], results: BulkResult[]) {
      setItems((all) => {
        const out: UploadItem[] = []
        const byKey = new Map(batch.map((b) => [b.key, b]))
        for (const it of all) {
          if (!byKey.has(it.key)) {
            out.push(it)
            continue
          }
          const mine = isZip(it.label)
            ? results.filter((r) => r.filename === it.label || r.filename.startsWith(`${it.label} › `))
            : results.filter((r) => r.filename === it.label).slice(0, 1)
          if (!mine.length) {
            out.push({ ...it, status: 'failed', message: 'No response for this file', progress: 0 })
            continue
          }
          for (const r of mine) {
            const status: ItemStatus =
              r.status === 'added' ? 'reading' : r.status === 'duplicate' ? 'duplicate' : r.status === 'skipped' ? 'skipped' : 'rejected'
            out.push({
              key: `${it.key}:${r.filename}`,
              label: r.filename,
              status,
              message:
                r.status === 'added'
                  ? r.saved_as && r.saved_as !== r.filename.split(' › ').pop()
                    ? `Saved as “${r.saved_as}”. Reading…`
                    : 'Reading…'
                  : r.message,
              progress: 1,
              relPath: r.rel_path,
            })
          }
        }
        return out
      })
      if (results.some((r) => r.status === 'added')) startPolling()
    }
  }, [patch, qc, startPolling])

  const add = useCallback(
    (files: File[]) => {
      const fresh: UploadItem[] = []
      let ignored = 0
      for (const f of files) {
        if (!isAccepted(f.name)) {
          ignored++
          continue
        }
        const limit = (isZip(f.name) ? MAX_ZIP_MB : MAX_FILE_MB) * 1024 * 1024
        const key = `u${++seq}`
        if (f.size > limit) {
          fresh.push({ key, label: f.name, status: 'rejected', message: `Larger than ${limit / 1048576} MB`, progress: 0 })
          continue
        }
        fresh.push({ key, label: f.name, status: 'queued', progress: 0, file: f })
      }
      if (fresh.length) {
        setItems((all) => [...fresh, ...all].slice(0, 3000)) // newest first; keep the list bounded
        queue.current.push(...fresh.filter((f) => f.status === 'queued'))
        void run()
      }
      return { accepted: fresh.length, ignored }
    },
    [run],
  )

  const retryFailed = useCallback(() => {
    const failed = items.filter((i) => i.status === 'failed' && i.file)
    if (!failed.length) return
    patch(
      failed.map((f) => f.key),
      { status: 'queued', message: undefined, progress: 0 },
    )
    queue.current.push(...failed.map((f) => ({ ...f, status: 'queued' as const })))
    void run()
  }, [items, patch, run])

  const clear = useCallback(() => {
    setItems((all) => all.filter((i) => ['queued', 'uploading', 'reading'].includes(i.status)))
  }, [])

  const busy = items.some((i) => ['queued', 'uploading', 'reading'].includes(i.status))
  const value = useMemo(() => ({ items, busy, add, retryFailed, clear }), [items, busy, add, retryFailed, clear])
  return <UploadCtx.Provider value={value}>{children}</UploadCtx.Provider>
}

export function useUploads() {
  const ctx = useContext(UploadCtx)
  if (!ctx) throw new Error('useUploads outside UploadProvider')
  return ctx
}

export function summarize(items: UploadItem[]) {
  const c = (s: ItemStatus[]) => items.filter((i) => s.includes(i.status)).length
  return {
    total: items.length,
    inFlight: c(['queued', 'uploading']),
    reading: c(['reading']),
    ready: c(['ready']),
    duplicate: c(['duplicate']),
    problems: c(['rejected', 'unreadable', 'failed']),
    skipped: c(['skipped']),
    failed: c(['failed']),
  }
}
