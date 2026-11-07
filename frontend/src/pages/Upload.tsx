import { useMutation } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, Copy, FileUp } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Link, useOutletContext } from 'react-router'
import { Button, Spinner, useToast } from '../components/ui'
import { api, type IndexStatus, type UploadResult } from '../lib/api'
import { cn } from '../lib/utils'

const ACCEPT = '.pdf,.docx,.doc'
const MAX_MB = 20

export default function UploadPage() {
  const { status } = useOutletContext<{ status: IndexStatus | null }>()
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [history, setHistory] = useState<UploadResult['results']>([])

  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: (r) => {
      setHistory((h) => [...r.results, ...h])
      if (r.added) toast(`${r.added} resume${r.added > 1 ? 's' : ''} added. Indexing now.`, 'ok')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const send = (list: FileList | File[] | null) => {
    if (!list) return
    const files = Array.from(list)
    const tooBig = files.filter((f) => f.size > MAX_MB * 1024 * 1024)
    const ok = files.filter((f) => f.size <= MAX_MB * 1024 * 1024)
    if (tooBig.length)
      setHistory((h) => [
        ...tooBig.map((f) => ({ filename: f.name, status: 'rejected' as const, message: `Larger than ${MAX_MB} MB` })),
        ...h,
      ])
    for (let i = 0; i < ok.length; i += 50) upload.mutate(ok.slice(i, i + 50))
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    send(e.dataTransfer.files)
  }

  const indexing = status && status.state !== 'idle' && status.state !== 'enhancing'

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight">Add resumes</h1>
      <p className="mt-1 text-sm text-muted">
        PDF, Word (DOCX) or older Word (DOC), up to {MAX_MB} MB each. Files are copied into your resume folder and
        indexed automatically. Existing files are never changed, and duplicates are detected.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cn(
          'mt-6 flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors',
          drag ? 'border-ink bg-ink-soft' : 'border-line-strong bg-surface',
        )}
        data-testid="dropzone"
      >
        <FileUp className="size-8 text-muted" aria-hidden />
        <p className="text-[15px] font-medium">Drop resumes here</p>
        <p className="text-sm text-muted">or</p>
        <Button variant="primary" onClick={() => input.current?.click()} busy={upload.isPending}>
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          data-testid="file-input"
          onChange={(e) => {
            send(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {indexing && (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted" data-testid="upload-indexing">
          <Spinner /> Indexing{status?.total ? ` ${status.done} of ${status.total}` : '…'} {status?.current}
        </p>
      )}

      {history.length > 0 && (
        <section className="mt-8">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">This session</h2>
            <Link to="/?sort=recent" className="text-sm font-medium text-ink underline underline-offset-2">
              See in library
            </Link>
          </div>
          <ul className="mt-3 divide-y divide-line border-y border-line" data-testid="upload-results">
            {history.map((r, i) => (
              <li key={`${r.filename}-${i}`} className="flex items-start gap-3 py-3 text-sm" data-status={r.status}>
                {r.status === 'added' && <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" />}
                {r.status === 'duplicate' && <Copy className="mt-0.5 size-4 shrink-0 text-muted" />}
                {r.status === 'rejected' && <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" />}
                <div className="min-w-0">
                  <p className="truncate font-medium">{r.filename}</p>
                  <p className={cn('text-[13px]', r.status === 'rejected' ? 'text-danger' : 'text-muted')}>
                    {r.status === 'added' && r.saved_as !== r.filename ? `Saved as “${r.saved_as}”. ` : ''}
                    {r.message}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
