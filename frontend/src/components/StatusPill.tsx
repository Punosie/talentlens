import * as Popover from '@radix-ui/react-popover'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, FolderSync, LoaderCircle, Pause, Play, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { api, type IndexStatus } from '../lib/api'
import { cn, timeAgo } from '../lib/utils'
import { Button, Progress, useToast } from './ui'

/** Plain-language library status in the header, with a popover for details and actions. */
export function StatusPill({ status }: { status: IndexStatus | null }) {
  const toast = useToast()
  const qc = useQueryClient()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
  const check = useMutation({
    mutationFn: (full: boolean) => api.refresh(full),
    onSuccess: (_d, full) => toast(full ? 'Rebuilding your library. Your files are not changed.' : 'Checking your folder for new resumes…'),
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const pause = useMutation({
    mutationFn: (paused: boolean) => api.setAiPaused(paused),
    onSuccess: (_d, paused) => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast(paused ? 'Smart reading paused' : 'Smart reading resumed')
    },
  })

  if (!status || status.state === 'no_folder') return null
  const reading = status.state === 'running' || status.state === 'queued'
  const enhancing = status.state === 'enhancing'
  const total = status.counts?.indexed ?? 0
  const aiLeft = Math.max(0, status.ai_total - status.ai_done)
  const llm = health.data?.llm
  const aiOn = !!llm?.available
  const unreadable = status.counts?.unreadable ?? 0

  const label = reading
    ? status.total
      ? `Reading resumes ${status.done}/${status.total}`
      : 'Checking folder…'
    : enhancing
      ? `Smart reading ${status.ai_done}/${status.ai_total}`
      : `${total} resume${total === 1 ? '' : 's'}`

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          data-testid="index-status"
          className="flex h-9 items-center gap-2 rounded-full border border-line-strong bg-surface px-3 text-[13px] font-medium shadow-e1 hover:bg-sunken"
          aria-label={`Library status: ${label}. Open details`}
        >
          {reading || enhancing ? (
            <LoaderCircle className={cn('size-4 animate-spin', enhancing ? 'text-[var(--seg-experience)]' : 'text-ink')} />
          ) : (
            <CircleCheck className="size-4 text-ok" />
          )}
          <span data-testid="index-status-line">{label}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="tl-enter z-50 w-[340px] rounded-[12px] border border-line bg-surface p-4 shadow-e2"
        >
          <h3 className="text-[15px] font-semibold">Your library</h3>
          <p className="mt-0.5 text-[13px] text-muted">
            {total} resume{total === 1 ? '' : 's'} searchable · updated {timeAgo(status.last_index_at)}
          </p>
          {reading && (
            <div className="mt-3">
              <Progress value={status.total ? status.done / status.total : 0.05} label="Reading resumes" />
              <p className="mt-1.5 truncate text-[12px] text-muted">{status.current || 'Looking for new files…'}</p>
            </div>
          )}
          {unreadable > 0 && (
            <p className="mt-3 flex items-start gap-2 rounded-md bg-danger-soft p-2.5 text-[12.5px] text-danger">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              {unreadable} file{unreadable === 1 ? '' : 's'} couldn't be read (empty, damaged or password-protected).
            </p>
          )}

          <div className="mt-4 border-t border-line pt-4">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-[var(--seg-experience)]" />
              <h4 className="text-[14px] font-semibold">Smart reading</h4>
            </div>
            <p className="mt-1 text-[12.5px] leading-snug text-muted">
              The local AI double-checks names, job titles and experience. It runs quietly in the background and nothing
              leaves this computer.
            </p>
            {aiOn ? (
              <>
                <Progress value={status.ai_total ? status.ai_done / status.ai_total : 1} className="mt-3" label="Smart reading" />
                <p className="mt-1.5 text-[12px] text-muted">
                  {aiLeft === 0
                    ? 'All resumes improved.'
                    : status.ai_paused
                      ? `Paused · ${aiLeft} left`
                      : `${status.ai_done} of ${status.ai_total} improved · ${aiLeft} left`}
                </p>
                {aiLeft > 0 && (
                  <Button size="sm" className="mt-2" onClick={() => pause.mutate(!status.ai_paused)} busy={pause.isPending}>
                    {status.ai_paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
                    {status.ai_paused ? 'Resume' : 'Pause'}
                  </Button>
                )}
              </>
            ) : (
              <p className="mt-2 text-[12.5px] text-muted">
                {llm?.mode === 'off' ? 'Turned off in ' : 'Not available right now. Everything else still works. See '}
                <Link to="/settings" className="font-medium text-ink underline">
                  Settings
                </Link>
                .
              </p>
            )}
          </div>

          <div className="mt-4 flex flex-col gap-2 border-t border-line pt-4">
            <Button onClick={() => check.mutate(false)} busy={check.isPending} data-testid="refresh-button">
              <FolderSync className="size-4" /> Check folder for new resumes
            </Button>
            <Button variant="ghost" size="sm" onClick={() => check.mutate(true)} data-testid="rebuild-button">
              <RefreshCw className="size-3.5" /> Rebuild library (re-read every file)
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
