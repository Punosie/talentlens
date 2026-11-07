import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, Copy, FileText, LoaderCircle, MinusCircle, RotateCw, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Progress } from '../components/ui'
import { cn } from '../lib/utils'
import { summarize, useUploads, type UploadItem } from './UploadContext'

/** Bottom-right upload panel (like Google Drive). Persists across pages. */
export function UploadTray() {
  const { items, busy, retryFailed, clear } = useUploads()
  const [open, setOpen] = useState(true)
  if (!items.length) return null
  const s = summarize(items)
  const done = s.ready + s.duplicate + s.problems + s.skipped
  const title = busy
    ? s.inFlight
      ? `Uploading ${items.length - s.inFlight} of ${items.length}…`
      : `Reading ${s.reading} resume${s.reading === 1 ? '' : 's'}…`
    : `${s.ready} added${s.duplicate ? ` · ${s.duplicate} already in library` : ''}${s.problems ? ` · ${s.problems} need attention` : ''}`

  return (
    <section
      aria-label="Uploads"
      data-testid="upload-tray"
      className="tl-enter fixed right-4 bottom-4 z-40 w-[min(400px,calc(100vw-32px))] overflow-hidden rounded-[12px] border border-line bg-surface shadow-e2"
    >
      <header className="flex items-center gap-2 border-b border-line bg-sunken/60 px-4 py-3">
        {busy ? <LoaderCircle className="size-4 animate-spin text-ink" /> : <CircleCheck className="size-4 text-ok" />}
        <h2 className="min-w-0 flex-1 truncate text-[14px] font-semibold" data-testid="upload-tray-title" aria-live="polite">
          {title}
        </h2>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="rounded p-1 text-muted hover:bg-sunken hover:text-text"
          aria-label={open ? 'Collapse uploads' : 'Expand uploads'}
        >
          {open ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </button>
        {!busy && (
          <button type="button" onClick={clear} className="rounded p-1 text-muted hover:bg-sunken hover:text-text" aria-label="Close uploads">
            <X className="size-4" />
          </button>
        )}
      </header>
      {busy && <Progress value={items.length ? done / items.length : 0} className="rounded-none" label="Overall upload progress" />}
      {open && (
        <>
          <ul className="max-h-[320px] divide-y divide-line overflow-y-auto" data-testid="upload-results">
            {items.slice(0, 300).map((it) => (
              <Row key={it.key} it={it} />
            ))}
          </ul>
          {(s.failed > 0 || (!busy && s.ready > 0)) && (
            <footer className="flex items-center justify-between gap-2 border-t border-line px-4 py-2.5 text-[13px]">
              {s.failed > 0 ? (
                <button type="button" onClick={retryFailed} className="inline-flex items-center gap-1.5 font-medium text-ink hover:underline">
                  <RotateCw className="size-3.5" /> Retry {s.failed} failed
                </button>
              ) : (
                <span className="text-muted">All set. New resumes are searchable now.</span>
              )}
              <Link to="/search?sort=recent" className="font-medium text-ink hover:underline">
                See them
              </Link>
            </footer>
          )}
        </>
      )}
    </section>
  )
}

const ICON: Record<UploadItem['status'], { icon: typeof FileText; cls: string; text: string }> = {
  queued: { icon: FileText, cls: 'text-muted', text: 'Waiting…' },
  uploading: { icon: LoaderCircle, cls: 'animate-spin text-ink', text: 'Uploading…' },
  reading: { icon: LoaderCircle, cls: 'animate-spin text-ink', text: 'Reading…' },
  ready: { icon: CircleCheck, cls: 'text-ok', text: 'Ready to search' },
  duplicate: { icon: Copy, cls: 'text-muted', text: 'Already in your library' },
  skipped: { icon: MinusCircle, cls: 'text-muted', text: 'Skipped' },
  rejected: { icon: CircleAlert, cls: 'text-danger', text: "Couldn't add" },
  unreadable: { icon: CircleAlert, cls: 'text-danger', text: "Couldn't read" },
  failed: { icon: CircleAlert, cls: 'text-danger', text: 'Upload failed' },
}

function Row({ it }: { it: UploadItem }) {
  const meta = ICON[it.status]
  const Icon = meta.icon
  const bad = ['rejected', 'unreadable', 'failed'].includes(it.status)
  return (
    <li className="flex items-start gap-3 px-4 py-2.5" data-status={it.status}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', meta.cls)} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium" title={it.label}>
          {it.label.split(' › ').pop()}
        </p>
        <p className={cn('truncate text-[12px]', bad ? 'text-danger' : 'text-muted')}>{it.message || meta.text}</p>
        {it.status === 'uploading' && <Progress value={it.progress} className="mt-1.5" label={`Uploading ${it.label}`} />}
      </div>
    </li>
  )
}
