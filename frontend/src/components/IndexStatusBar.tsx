import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, Pause, Play, RefreshCw, Sparkles } from 'lucide-react'
import { api, type IndexStatus } from '../lib/api'
import { cn, timeAgo } from '../lib/utils'
import { useToast } from './ui'

export function IndexStatusBar({ status }: { status: IndexStatus | null }) {
  const toast = useToast()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
  const refresh = useMutation({
    mutationFn: (full: boolean) => api.refresh(full),
    onSuccess: (_d, full) => toast(full ? 'Full re-index started' : 'Checking the folder for changes…'),
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const ai = useMutation({
    mutationFn: (paused: boolean) => api.setAiPaused(paused),
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const busy = status && (status.state === 'running' || status.state === 'queued')
  const enhancing = status?.state === 'enhancing'
  const total = status?.counts?.indexed ?? 0
  const llmOk = health.data?.llm.available

  let line: string
  if (!status) line = 'Connecting…'
  else if (status.state === 'running')
    line = status.total ? `Indexing ${status.done} of ${status.total}` : 'Scanning folder…'
  else if (status.state === 'queued') line = 'Index update queued'
  else if (enhancing) line = `AI reading resume ${status.done + 1} of ${status.total}`
  else line = `${total} resume${total === 1 ? '' : 's'} · updated ${timeAgo(status.last_index_at)}`

  return (
    <div className="flex items-center gap-2" data-testid="index-status">
      <div className="hidden min-w-0 flex-col items-end leading-tight sm:flex">
        <span className="text-[13px] font-medium" data-testid="index-status-line">
          {line}
        </span>
        <span className="max-w-[320px] truncate text-[12px] text-muted">
          {busy && status?.current
            ? status.current
            : enhancing
              ? status?.current || 'Refining skills, titles and experience'
              : status?.ai_pending
                ? status.ai_paused
                  ? `AI paused · ${status.ai_pending} waiting`
                  : llmOk
                    ? `${status.ai_pending} waiting for AI`
                    : 'Local AI offline · using rules'
                : llmOk
                  ? 'All resumes enriched by local AI'
                  : health.data
                    ? 'Local AI offline · using rules'
                    : ''}
        </span>
      </div>

      <div className="flex items-center rounded-md border border-line-strong bg-surface">
        <button
          type="button"
          onClick={() => refresh.mutate(false)}
          className="flex h-9 items-center gap-2 rounded-l-md px-3 text-sm hover:bg-sunken"
          aria-label="Refresh index"
          title="Re-scan the resume folder for new or changed files"
          data-testid="refresh-button"
        >
          <RefreshCw className={cn('size-4', (busy || refresh.isPending) && 'animate-spin')} />
          <span className="hidden md:inline">Refresh</span>
        </button>
        <Dropdown.Root>
          <Dropdown.Trigger
            className="flex h-9 items-center rounded-r-md border-l border-line-strong px-2 hover:bg-sunken"
            aria-label="More index actions"
          >
            <ChevronDown className="size-4" />
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content
              align="end"
              sideOffset={6}
              className="z-50 min-w-[240px] rounded-md border border-line-strong bg-surface p-1 text-sm shadow-lg"
            >
              <Dropdown.Item
                onSelect={() => refresh.mutate(true)}
                className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 outline-none data-[highlighted]:bg-sunken"
              >
                <RefreshCw className="mt-0.5 size-4" />
                <span>
                  Full re-index
                  <span className="block text-[12px] text-muted">Re-read every file (AI results are kept)</span>
                </span>
              </Dropdown.Item>
              <Dropdown.Item
                onSelect={() => ai.mutate(!status?.ai_paused)}
                className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 outline-none data-[highlighted]:bg-sunken"
              >
                {status?.ai_paused ? <Play className="mt-0.5 size-4" /> : <Pause className="mt-0.5 size-4" />}
                <span>
                  {status?.ai_paused ? 'Resume AI enrichment' : 'Pause AI enrichment'}
                  <span className="block text-[12px] text-muted">Background reading by the local LLM</span>
                </span>
              </Dropdown.Item>
              <div className="mt-1 border-t border-line px-2 pt-2 pb-1 text-[12px] text-muted">
                <Sparkles className="mr-1 inline size-3.5" />
                {health.data
                  ? llmOk
                    ? `Local AI: ${health.data.llm.model}`
                    : (health.data.llm.error ?? 'Local AI off')
                  : 'Checking local AI…'}
              </div>
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      </div>
    </div>
  )
}
