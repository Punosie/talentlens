import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Lock, Monitor, Moon, RefreshCw, Sparkles, Sun } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { ConnectionsSettings } from '../components/ConnectionsSettings'
import { FolderPicker } from '../components/FolderPicker'
import { Button, Card, ConfirmDialog, PageHeader, Skeleton, useToast } from '../components/ui'
import { api } from '../lib/api'
import { cn } from '../lib/utils'

function Section({ title, description, children }: { title: string; description: ReactNode; children: ReactNode }) {
  return (
    <Card as="section" className="grid gap-6 p-6 md:grid-cols-[260px_minmax(0,1fr)] md:p-8">
      <div>
        <h2 className="text-[16px] font-semibold">{title}</h2>
        <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{description}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </Card>
  )
}

type Theme = 'light' | 'dark' | 'system'
function currentTheme(): Theme {
  try {
    return (localStorage.getItem('tl-theme') as Theme) || 'system'
  } catch {
    return 'system'
  }
}
function applyTheme(t: Theme) {
  try {
    if (t === 'system') localStorage.removeItem('tl-theme')
    else localStorage.setItem('tl-theme', t)
  } catch {
    /* private mode */
  }
  const dark = t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const s = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [changing, setChanging] = useState(false)
  const [theme, setTheme] = useState<Theme>(currentTheme)
  const [rebuild, setRebuild] = useState(false)

  const ai = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['health'] })
      toast('Settings saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const doRebuild = useMutation({
    mutationFn: () => api.refresh(true),
    onSuccess: () => {
      setRebuild(false)
      toast('Rebuilding your library. Your files are not changed.')
    },
  })

  const d = s.data
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 md:px-8">
      <PageHeader title="Settings" description="Choose where your resumes live and how TalentLens works on this computer." />
      {!d && <Skeleton className="h-48" />}
      {d && (
        <>
          <Section title="Resume folder" description="The folder TalentLens reads resumes from. New resumes you add are saved here too. Existing files are never changed.">
            <div className="flex items-start gap-3 rounded-md bg-sunken p-3">
              <FolderOpen className="mt-0.5 size-5 shrink-0 text-ink" />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[13px] break-all" data-testid="current-folder">
                  {d.cv_dir ?? 'Not chosen yet'}
                </p>
                <p className="mt-0.5 text-[12px] text-muted">
                  {d.cv_dir_source === 'config'
                    ? 'Set in the configuration file (.env), so it can only be changed there.'
                    : d.cv_dir_source === 'auto'
                      ? 'Found automatically.'
                      : d.cv_dir
                        ? 'Chosen by you.'
                        : ''}
                </p>
              </div>
              {d.cv_dir_source === 'config' && <Lock className="size-4 text-muted" />}
            </div>
            {d.cv_dir_source !== 'config' && (
              <div className="mt-4">
                {changing ? (
                  <FolderPicker
                    initial={d.cv_dir}
                    platform={d.platform}
                    submitLabel="Switch to this folder"
                    onChosen={() => {
                      setChanging(false)
                      qc.invalidateQueries()
                      toast('Folder changed. Reading its resumes now.')
                    }}
                  />
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => setChanging(true)} data-testid="change-folder">
                      Change folder…
                    </Button>
                    {d.cv_dir && (
                      <Button variant="ghost" onClick={() => api.revealFolder().catch(() => toast('Could not open the folder', 'error'))}>
                        Show in {d.platform === 'mac' ? 'Finder' : 'File Explorer'}
                      </Button>
                    )}
                  </div>
                )}
                <p className="mt-3 text-[12.5px] text-muted">
                  Each folder keeps its own library. Switching back later is instant, and nothing is lost.
                </p>
              </div>
            )}
          </Section>

          <Section
            title="Smart reading (AI)"
            description="A local AI double-checks names, job titles and experience, and explains match scores. It runs entirely on this computer."
          >
            <div className="flex items-center gap-2 text-[14px]">
              <Sparkles className="size-4 text-[var(--seg-experience)]" />
              <span className="font-medium">Status:</span>
              <span data-testid="ai-status">
                {!d.ai.enabled
                  ? 'Off'
                  : d.ai.available
                    ? `Ready${d.ai.paused ? ' (paused)' : ''}`
                    : 'Not available'}
              </span>
            </div>
            {d.ai.enabled && !d.ai.available && d.ai.error && <p className="mt-1 text-[12.5px] text-muted">{d.ai.error}</p>}

            {!d.ai.locked && (
              <>
                <label className="mt-4 flex items-center gap-3">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--ink)]"
                    checked={d.ai.enabled}
                    onChange={(e) => ai.mutate({ ai_enabled: e.target.checked })}
                    data-testid="ai-toggle"
                  />
                  <span className="text-[14px]">Use smart reading</span>
                </label>
                <p className="mt-1 pl-7 text-[12.5px] text-muted">When off, everything still works using fast automatic reading.</p>

                {d.ai.enabled && (
                  <fieldset className="mt-5">
                    <legend className="text-[13px] font-semibold">Quality</legend>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {d.ai.models.map((m) => (
                        <label
                          key={m.id}
                          className={cn(
                            'flex cursor-pointer flex-col gap-0.5 rounded-[10px] border p-3',
                            d.ai.model === m.id ? 'border-ink bg-ink-soft/40' : 'border-line-strong hover:border-ink',
                          )}
                        >
                          <span className="flex items-center gap-2 text-[14px] font-medium">
                            <input
                              type="radio"
                              name="model"
                              className="accent-[var(--ink)]"
                              checked={d.ai.model === m.id}
                              onChange={() => ai.mutate({ ollama_model: m.id })}
                            />
                            {m.label}
                          </span>
                          <span className="pl-6 text-[12.5px] text-muted">{m.hint}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}
              </>
            )}
            {d.ai.locked && <p className="mt-3 text-[12.5px] text-muted">Set in the configuration file (.env).</p>}
            {d.device && (
              <p className="mt-4 text-[12.5px] text-muted" data-testid="device-info">
                Search runs on the {d.device.active === 'cuda' ? `GPU (${d.device.benchmark?.gpu_name ?? 'NVIDIA'})` : 'CPU'}
                {d.device.benchmark?.cpu_per_s
                  ? ` · measured at setup: CPU ${d.device.benchmark.cpu_per_s}/s${d.device.benchmark.cuda_per_s ? `, GPU ${d.device.benchmark.cuda_per_s}/s` : ''}`
                  : ''}
                . Run <code>talentlens benchmark</code> to measure again.
              </p>
            )}
          </Section>

          <Section
            title="Connections database"
            description="Bring in your LinkedIn connections from MongoDB so you can search and match them with your resumes. Resumes you add here are saved to the database too, linked to the right person."
          >
            <ConnectionsSettings settings={d} />
          </Section>

          <Section title="Appearance" description="Light, dark, or follow your computer's setting.">
            <div className="inline-flex rounded-[10px] border border-line-strong p-1" role="radiogroup" aria-label="Theme">
              {(
                [
                  ['light', 'Light', Sun],
                  ['dark', 'Dark', Moon],
                  ['system', 'System', Monitor],
                ] as const
              ).map(([v, l, Icon]) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={theme === v}
                  onClick={() => {
                    setTheme(v)
                    applyTheme(v)
                  }}
                  className={cn(
                    'flex items-center gap-2 rounded-[7px] px-3 py-1.5 text-[14px]',
                    theme === v ? 'bg-ink text-on-ink' : 'text-muted hover:text-text',
                  )}
                >
                  <Icon className="size-4" /> {l}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Data & privacy" description="TalentLens keeps its own working data separate from your resumes. Nothing is sent over the internet.">
            <dl className="space-y-2 text-[13.5px]">
              <div>
                <dt className="text-muted">Working data</dt>
                <dd className="font-mono text-[12.5px] break-all">{d.data_dir}</dd>
              </div>
              {d.provenance_csv && (
                <div>
                  <dt className="text-muted">Resume source list (read only)</dt>
                  <dd className="font-mono text-[12.5px] break-all">{d.provenance_csv}</dd>
                </div>
              )}
            </dl>
            <Button className="mt-4" onClick={() => setRebuild(true)}>
              <RefreshCw className="size-4" /> Rebuild library
            </Button>
            <p className="mt-1.5 text-[12.5px] text-muted">Re-reads every resume. Useful if something looks out of date. Smart reading results are kept.</p>
          </Section>

          <p className="text-center text-[12px] text-muted">TalentLens {d.version} · MIT licensed · runs locally</p>
        </>
      )}
      <ConfirmDialog
        open={rebuild}
        onOpenChange={setRebuild}
        title="Rebuild your library?"
        description="TalentLens will re-read every resume. This can take a few minutes for large libraries. Your files are not changed."
        confirmLabel="Rebuild"
        busy={doRebuild.isPending}
        onConfirm={() => doRebuild.mutate()}
      />
    </div>
  )
}
