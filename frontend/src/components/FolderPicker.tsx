import { useMutation } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, FolderOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type AppSettings } from '../lib/api'
import { cn } from '../lib/utils'
import { Button, Input, Spinner } from './ui'

const EXAMPLE: Record<AppSettings['platform'], string> = {
  windows: 'C:\\Users\\you\\OneDrive\\Desktop\\CVs',
  mac: '/Users/you/Desktop/CVs',
  linux: '/home/you/CVs',
}

/** Browse (native dialog) or type a folder path, with a live "Found N resumes" check. */
export function FolderPicker({
  initial,
  platform = 'windows',
  submitLabel = 'Use this folder',
  onChosen,
}: {
  initial?: string | null
  platform?: AppSettings['platform']
  submitLabel?: string
  onChosen: (settings: AppSettings) => void
}) {
  const [path, setPath] = useState(initial ?? '')
  const [check, setCheck] = useState<{ ok: boolean; message: string; count: number } | null>(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    if (!path.trim()) return
    const t = setTimeout(() => {
      setChecking(true)
      api
        .checkFolder(path.trim())
        .then(setCheck)
        .catch(() => setCheck(null))
        .finally(() => setChecking(false))
    }, 350)
    return () => clearTimeout(t)
  }, [path])

  const browse = useMutation({
    mutationFn: api.pickFolder,
    onSuccess: (r) => r.path && setPath(r.path),
  })
  const save = useMutation({
    mutationFn: () => api.updateSettings({ cv_dir: path.trim() }),
    onSuccess: onChosen,
  })

  return (
    <div className="space-y-3" data-testid="folder-picker">
      <div className="flex gap-2">
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder={EXAMPLE[platform]}
          aria-label="Resume folder path"
          data-testid="folder-path"
          className="font-mono text-[13px]"
          spellCheck={false}
        />
        <Button onClick={() => browse.mutate()} busy={browse.isPending} data-testid="folder-browse">
          <FolderOpen className="size-4" /> Browse…
        </Button>
      </div>
      {browse.isPending && (
        <p className="text-[13px] text-muted">A folder window opened. It may be behind this browser window.</p>
      )}
      {browse.error && <p className="text-[13px] text-danger">{(browse.error as Error).message}</p>}
      <div className="min-h-5 text-[13px]" aria-live="polite" data-testid="folder-check">
        {!path.trim() ? null : checking ? (
          <span className="inline-flex items-center gap-2 text-muted">
            <Spinner /> Checking folder…
          </span>
        ) : check ? (
          <span className={cn('inline-flex items-start gap-1.5', check.ok ? 'text-ok' : 'text-danger')}>
            {check.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}
            {check.message}
          </span>
        ) : null}
      </div>
      {save.error && <p className="text-[13px] text-danger">{(save.error as Error).message}</p>}
      <Button
        variant="primary"
        onClick={() => save.mutate()}
        busy={save.isPending}
        disabled={!path.trim() || !check?.ok}
        data-testid="folder-save"
      >
        {submitLabel}
      </Button>
    </div>
  )
}
