import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, ChevronDown, Download, FileText, ListChecks, Pencil, Save, Sparkles, Upload, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { CandidateProfile, SourceBadges } from '../components/CandidateProfile'
import { FacetPicker } from '../components/FacetPicker'
import { SEGMENTS, ScoreBar } from '../components/ScoreBar'
import { Avatar, Button, Card, Chip, Empty, HelpDot, Input, Label, Modal, Skeleton, Spinner, Textarea, useToast } from '../components/ui'
import { api, type RankedCV, type Requirements, type ShortlistResult } from '../lib/api'
import { cn, displayName, downloadBlob, matchLabel, matchReason } from '../lib/utils'

type Step = 0 | 1 | 2
type Explanation = { reason: string; strengths: string[]; gaps: string[] }

const EMPTY_REQ: Requirements = {
  title: null,
  must_have_skills: [],
  nice_to_have_skills: [],
  min_years: null,
  max_years: null,
  locations: [],
  domains: [],
  summary: null,
  source: 'user',
}

const SEG_HELP: Record<string, string> = {
  semantic: 'How closely the whole resume matches the job overall (meaning, not just keywords).',
  must: 'Share of the must-have skills found in the resume.',
  nice: 'Share of the nice-to-have skills found.',
  experience: 'Full points when experience is in the range you asked for; partial when close.',
  domain: 'Has worked in the industry you asked for.',
  location: 'Full points in the same city, partial in the same country.',
}

function parseExplanation(text: string): Explanation {
  const grab = (label: string) => {
    const m = text.match(new RegExp(`${label}:\\s*([\\s\\S]*?)(?=\\n\\s*(Verdict|Strengths|Gaps):|$)`, 'i'))
    return m ? m[1].trim() : ''
  }
  const list = (s: string) =>
    s
      .split(/;|\n/)
      .map((x) => x.replace(/^[-•*\s]+/, '').trim())
      .filter((x) => x && x.toLowerCase() !== 'none')
  const reason = grab('Verdict') || (/(Strengths|Gaps):/i.test(text) ? '' : text.trim())
  return { reason, strengths: list(grab('Strengths')), gaps: list(grab('Gaps')) }
}

function useSessionState<T>(key: string, initial: T) {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(v))
    } catch {
      /* quota / private mode */
    }
  }, [key, v])
  return [v, setV] as const
}

export default function MatchPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const [step, setStep] = useSessionState<Step>('m-step', 0)
  const [jdInput, setJdInput] = useSessionState('m-input', '')
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [jdText, setJdText] = useSessionState('m-jd', '')
  const [req, setReq] = useSessionState<Requirements | null>('m-req', null)
  const [result, setResult] = useSessionState<ShortlistResult | null>('m-result', null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [openId, setOpenId] = useState<number | null>(null)
  const [explanations, setExplanations] = useState<Record<number, Explanation | 'loading' | string>>({})
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [aiOffer, setAiOffer] = useState<Requirements | null>(null)
  const dirtyRef = useRef(false)
  const stepRef = useRef<Step>(step)
  useEffect(() => {
    stepRef.current = step
  }, [step])
  const openSave = (title: string | null) => {
    setSaveName(title || 'Shortlist')
    setSaveOpen(true)
  }

  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const llmOk = !!health.data?.llm.available
  const hasLinkedIn = (facets.data?.sources ?? []).some((s) => s.value === 'linkedin' && s.count > 0)
  const [pool, setPool] = useState<'' | 'file' | 'linkedin'>('')
  const [via, setVia] = useState<string[]>([])
  const scope = { sources: pool ? [pool] : [], owners: pool === 'file' ? [] : via }

  // --- ranking: instant first, refined second -------------------------------------
  const [refining, setRefining] = useState(false)
  const rank = useMutation({
    mutationFn: async ({ r, jd }: { r: Requirements; jd: string }) => {
      const quick = await api.shortlist(r, jd, 100, false, scope)
      setResult(quick)
      setRefining(true)
      try {
        return await api.shortlist(r, jd, 100, true, scope)
      } finally {
        setRefining(false)
      }
    },
    onSuccess: (r) => {
      setResult(r)
      setExplanations({})
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const aiParse = useMutation({
    mutationFn: (input: { text?: string; file?: File }) => api.parseJd({ ...input, mode: 'ai' }),
    onSuccess: (r) => {
      if (r.warning) return
      if (dirtyRef.current) {
        setAiOffer(r.requirements)
        return
      }
      setReq(r.requirements)
      toast('Smart reading improved the requirements')
      if (stepRef.current === 2) rank.mutate({ r: r.requirements, jd: r.jd_text })
    },
  })

  const parse = useMutation({
    mutationFn: (input: { text?: string; file?: File }) => api.parseJd({ ...input, mode: 'rules' }),
    onSuccess: (r, input) => {
      setJdText(r.jd_text)
      setReq(r.requirements)
      dirtyRef.current = false
      setAiOffer(null)
      setResult(null)
      setSelected(new Set())
      setStep(1)
      if (llmOk) aiParse.mutate(input)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const edit = (patch: Partial<Requirements>) => {
    setReq((r) => ({ ...(r ?? EMPTY_REQ), ...patch, source: 'user' }))
    dirtyRef.current = true
  }

  const readJd = () => {
    if (jdFile) parse.mutate({ file: jdFile })
    else if (jdInput.trim().length >= 20) parse.mutate({ text: jdInput })
    else toast('Paste the job description or choose a file first', 'error')
  }

  const showCandidates = () => {
    if (!req) return
    setStep(2)
    rank.mutate({ r: req, jd: jdText })
  }

  const explain = async (cv: RankedCV) => {
    if (!req) return
    setExplanations((e) => ({ ...e, [cv.id]: 'loading' }))
    try {
      await api.explainStream(cv.id, req, (text) => setExplanations((e) => ({ ...e, [cv.id]: parseExplanation(text) })))
    } catch (err) {
      setExplanations((e) => ({ ...e, [cv.id]: (err as Error).message }))
    }
  }

  const chosen = useMemo(() => {
    const items = result?.items ?? []
    return selected.size ? items.filter((i) => selected.has(i.id)) : items
  }, [result, selected])

  const save = useMutation({
    mutationFn: (name: string) => api.saveShortlist({ name, jd_text: jdText, requirements: req!, results: chosen }),
    onSuccess: (r) => {
      toast(`Saved “${r.name}” with ${chosen.length} candidates`, 'ok')
      setSaveOpen(false)
      navigate(`/saved/${r.id}`)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const exportCsv = async () => {
    if (!req) return
    const name = (req.title || 'candidates').slice(0, 60)
    try {
      downloadBlob(await api.exportUnsaved({ name, jd_text: jdText, requirements: req, results: chosen }), `${name}.csv`)
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  const reset = () => {
    setReq(null)
    setResult(null)
    setJdText('')
    setJdInput('')
    setJdFile(null)
    setSelected(new Set())
    setStep(0)
  }

  const skillOptions = facets.data?.skills ?? []
  const locationOptions = [
    ...(facets.data?.countries ?? []).map((c) => ({ value: c.value, count: c.count, hint: 'country' })),
    ...(facets.data?.cities ?? []).map((c) => ({ value: c.value, count: c.count, hint: c.country })),
  ]

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight md:text-[28px]">Match to a job</h1>
          <p className="mt-1 text-[15px] text-muted">Find the best people in your library for a job description.</p>
        </div>
        {step > 0 && (
          <Button variant="ghost" onClick={reset} data-testid="new-jd">
            <X className="size-4" /> Start over
          </Button>
        )}
      </div>

      <Stepper step={step} onGo={(s) => (s < step || (s === 1 && req) ? setStep(s) : undefined)} />

      {/* ---------- step 1: job description ---------- */}
      {step === 0 && (
        <Card className="mt-6 p-6 md:p-8">
          <JdInput
            text={jdInput}
            onText={setJdInput}
            file={jdFile}
            onFile={setJdFile}
          />
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-muted">
              {llmOk ? 'TalentLens reads the requirements instantly, then smart reading double-checks them.' : 'Requirements are read automatically. You can adjust them next.'}
            </p>
            <Button variant="primary" size="lg" onClick={readJd} busy={parse.isPending} data-testid="jd-submit">
              Read requirements <ArrowRight className="size-4" />
            </Button>
          </div>
        </Card>
      )}

      {/* ---------- step 2: requirements ---------- */}
      {step === 1 && req && (
        <Card className="mt-6 p-6 md:p-8" >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[18px] font-semibold">Check the requirements</h2>
              <p className="mt-1 text-[14px] text-muted">These are what TalentLens found in the job description. Add or remove anything, then continue.</p>
            </div>
            {aiParse.isPending && (
              <span className="inline-flex items-center gap-2 rounded-full bg-sunken px-3 py-1 text-[12.5px] text-muted" data-testid="ai-refining">
                <Spinner className="size-3.5" /> Smart reading is double-checking…
              </span>
            )}
          </div>

          {aiOffer && (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border-l-2 border-mark bg-mark-soft px-4 py-3 text-sm">
              <Sparkles className="size-4" /> Smart reading suggested slightly different requirements. Your edits were kept.
              <Button
                size="sm"
                onClick={() => {
                  setReq(aiOffer)
                  setAiOffer(null)
                  dirtyRef.current = false
                }}
              >
                Use suggestion
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setAiOffer(null)}>Keep mine</Button>
            </div>
          )}

          <div className="mt-6 grid gap-x-8 gap-y-6 md:grid-cols-2" data-testid="requirements">
            <div className="md:col-span-2">
              <Label htmlFor="req-title">Job title</Label>
              <Input id="req-title" aria-label="Role" value={req.title ?? ''} onChange={(e) => edit({ title: e.target.value || null })} placeholder="e.g. Senior Data Engineer" />
            </div>
            <Group label="Must-have skills" hint="Candidates are scored mostly on these.">
              <FacetPicker label="Must-have skills" testId="req-must" options={skillOptions} selected={req.must_have_skills} onChange={(v) => edit({ must_have_skills: v })} allowCustom />
            </Group>
            <Group label="Nice-to-have skills" hint="A bonus, but not required.">
              <FacetPicker label="Nice-to-have skills" testId="req-nice" options={skillOptions} selected={req.nice_to_have_skills} onChange={(v) => edit({ nice_to_have_skills: v })} allowCustom />
            </Group>
            <Group label="Years of experience" hint="Leave empty if it doesn't matter.">
              <div className="flex items-center gap-2">
                <Input type="number" min={0} max={50} placeholder="Min" aria-label="Minimum years required" className="h-9" value={req.min_years ?? ''} onChange={(e) => edit({ min_years: e.target.value === '' ? null : Number(e.target.value) })} />
                <span className="text-muted">to</span>
                <Input type="number" min={0} max={50} placeholder="Max" aria-label="Maximum years" className="h-9" value={req.max_years ?? ''} onChange={(e) => edit({ max_years: e.target.value === '' ? null : Number(e.target.value) })} />
              </div>
            </Group>
            <Group label="Location" hint="City or country. Leave empty for anywhere.">
              <FacetPicker label="Location" testId="req-location" options={locationOptions} selected={req.locations} onChange={(v) => edit({ locations: v })} allowCustom />
            </Group>
            <Group label="Industry" hint="Experience in this industry scores higher.">
              <FacetPicker label="Industry" testId="req-domain" options={facets.data?.domains ?? []} selected={req.domains} onChange={(v) => edit({ domains: v })} />
            </Group>
            {hasLinkedIn && (
              <Group label="Search in" hint="Your resumes, your LinkedIn connections, or both.">
                <div className="flex rounded-md border border-line p-0.5 text-[13px]" role="group" aria-label="Search in">
                  {(
                    [
                      ['', 'Everyone'],
                      ['file', 'Resumes'],
                      ['linkedin', 'LinkedIn connections'],
                    ] as const
                  ).map(([v, label]) => (
                    <button
                      key={v || 'all'}
                      type="button"
                      aria-pressed={pool === v}
                      data-testid={`match-pool-${v || 'all'}`}
                      onClick={() => setPool(v)}
                      className={cn('flex-1 rounded px-2 py-1', pool === v ? 'bg-ink text-on-ink' : 'text-muted hover:text-text')}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {pool !== 'file' && (facets.data?.owners?.length ?? 0) > 1 && (
                  <div className="mt-2">
                    <FacetPicker label="Connected via" testId="match-owner" options={facets.data?.owners ?? []} selected={via} onChange={setVia} placeholder="Any LinkedIn account…" />
                  </div>
                )}
              </Group>
            )}
          </div>

          <details className="mt-6 text-sm">
            <summary className="cursor-pointer font-medium text-ink">Show the job description</summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-sunken p-3 font-sans text-[13px] whitespace-pre-wrap">{jdText}</pre>
          </details>

          <div className="mt-6 flex justify-between gap-3 border-t border-line pt-5">
            <Button variant="ghost" onClick={() => setStep(0)}>
              <ArrowLeft className="size-4" /> Back
            </Button>
            <Button variant="primary" size="lg" onClick={showCandidates} data-testid="show-candidates">
              Show candidates <ArrowRight className="size-4" />
            </Button>
          </div>
        </Card>
      )}

      {/* ---------- step 3: candidates ---------- */}
      {step === 2 && req && (
        <div className="mt-6">
          <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="min-w-0">
              <p className="truncate text-[15px] font-semibold">{req.title || 'Your job'}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {req.must_have_skills.slice(0, 8).map((s) => (
                  <Chip key={s} tone="ink">{s}</Chip>
                ))}
                {req.min_years ? <Chip tone="outline">{req.min_years}+ yrs</Chip> : null}
                {req.locations.map((l) => (
                  <Chip key={l} tone="outline">{l}</Chip>
                ))}
              </div>
            </div>
            <Button onClick={() => setStep(1)} data-testid="edit-requirements">
              <Pencil className="size-4" /> Edit requirements
            </Button>
          </Card>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] font-medium" data-testid="shortlist-count" aria-live="polite">
              {!result ? 'Finding candidates…' : `${result.total} candidates ranked`}
              {refining && <span className="ml-2 inline-flex items-center gap-1.5 text-[13px] font-normal text-muted"><Spinner className="size-3.5" /> fine-tuning the order…</span>}
              {result?.refined && !refining && <span className="ml-2 inline-flex items-center gap-1 text-[13px] font-normal text-muted"><Check className="size-3.5" /> order fine-tuned</span>}
            </p>
            {result && result.items.length > 0 && (
              <div className="flex gap-2">
                <Button size="sm" onClick={exportCsv} data-testid="export-csv">
                  <Download className="size-4" /> Export {selected.size ? selected.size : 'all'} to Excel (CSV)
                </Button>
                <Button size="sm" variant="primary" onClick={() => openSave(req.title)} data-testid="save-open">
                  <Save className="size-4" /> Save {selected.size ? selected.size : 'list'}
                </Button>
              </div>
            )}
          </div>

          {!result && (
            <ul className="mt-4 space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <li key={i} className="flex gap-4 rounded-[10px] border border-line bg-surface p-5">
                  <Skeleton className="size-11 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-3 w-2/3" />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {result && result.items.length === 0 && (
            <div className="mt-6">
              <Empty icon={<ListChecks className="size-6" />} title="No candidates found" action={<Button onClick={() => setStep(1)}>Edit requirements</Button>}>
                Try fewer must-have skills or remove the location.
              </Empty>
            </div>
          )}

          <ol className="mt-4 space-y-3" data-testid="shortlist-results">
            {result?.items.map((cv) => (
              <CandidateRow
                key={cv.id}
                cv={cv}
                req={req}
                weights={result.weights}
                checked={selected.has(cv.id)}
                onCheck={(on) =>
                  setSelected((s) => {
                    const n = new Set(s)
                    if (on) n.add(cv.id)
                    else n.delete(cv.id)
                    return n
                  })
                }
                onOpen={() => setOpenId(cv.id)}
                explanation={explanations[cv.id]}
                onExplain={llmOk ? () => explain(cv) : undefined}
              />
            ))}
          </ol>
        </div>
      )}

      {selected.size > 0 && step === 2 && (
        <div className="tl-enter fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full bg-[#1d2528] py-2 pr-2 pl-4 text-sm whitespace-nowrap text-white shadow-e2 sm:gap-3 sm:pl-5" data-testid="bulk-bar">
          <span className="font-medium">{selected.size} selected</span>
          <Button size="sm" variant="secondary" onClick={exportCsv}>
            <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
          <Button size="sm" className="bg-mark text-[#12181a] hover:opacity-90" onClick={() => openSave(req?.title ?? null)}>
            <Save className="size-4" /> <span className="sr-only sm:not-sr-only">Save list</span>
          </Button>
          <button type="button" className="rounded-full p-1.5 hover:bg-white/10" onClick={() => setSelected(new Set())} aria-label="Clear selection">
            <X className="size-4" />
          </button>
        </div>
      )}

      <Modal
        open={saveOpen}
        onOpenChange={setSaveOpen}
        title="Save this list"
        description={`${chosen.length} candidate${chosen.length === 1 ? '' : 's'} will be saved so you can come back to them, share or export later.`}
        footer={
          <>
            <Button onClick={() => setSaveOpen(false)}>Cancel</Button>
            <Button variant="primary" busy={save.isPending} disabled={!saveName.trim()} onClick={() => save.mutate(saveName.trim())} data-testid="save-confirm">
              Save list
            </Button>
          </>
        }
      >
        <Label htmlFor="save-name">List name</Label>
        <Input id="save-name" autoFocus value={saveName} onChange={(e) => setSaveName(e.target.value)} data-testid="save-name" onKeyDown={(e) => e.key === 'Enter' && saveName.trim() && save.mutate(saveName.trim())} />
      </Modal>

      <CandidateProfile cvId={openId} onClose={() => setOpenId(null)} highlight={req ? [...req.must_have_skills, ...req.nice_to_have_skills] : []} />
    </div>
  )
}

function Stepper({ step, onGo }: { step: Step; onGo: (s: Step) => void }) {
  const steps = ['Job description', 'Requirements', 'Candidates']
  return (
    <ol className="flex items-center gap-2" aria-label="Steps">
      {steps.map((label, i) => {
        const state = i < step ? 'done' : i === step ? 'current' : 'todo'
        return (
          <li key={label} className="flex flex-1 items-center gap-2">
            <button
              type="button"
              onClick={() => onGo(i as Step)}
              aria-current={state === 'current' ? 'step' : undefined}
              disabled={state === 'todo'}
              className="flex items-center gap-2 text-left disabled:cursor-default"
            >
              <span
                className={cn(
                  'flex size-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold',
                  state === 'done' && 'bg-ok text-white',
                  state === 'current' && 'bg-ink text-on-ink',
                  state === 'todo' && 'border border-line-strong text-muted',
                )}
              >
                {state === 'done' ? <Check className="size-4" /> : i + 1}
              </span>
              <span className={cn('hidden text-[14px] sm:inline', state === 'current' ? 'font-semibold' : 'text-muted')}>{label}</span>
            </button>
            {i < steps.length - 1 && <span className={cn('h-px flex-1', i < step ? 'bg-ok' : 'bg-line-strong')} />}
          </li>
        )
      })}
    </ol>
  )
}

function JdInput({ text, onText, file, onFile }: { text: string; onText: (t: string) => void; file: File | null; onFile: (f: File | null) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)} onDrop={onDrop}>
      <Label htmlFor="jd" hint="Paste the full text, or upload the job description as a PDF, Word or text file.">
        Job description
      </Label>
      {file ? (
        <div className="flex items-center gap-3 rounded-[10px] border border-line-strong bg-sunken p-4">
          <FileText className="size-6 text-ink" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{file.name}</p>
            <p className="text-[12px] text-muted">{(file.size / 1024).toFixed(0)} KB · ready to read</p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => onFile(null)}>
            Remove
          </Button>
        </div>
      ) : (
        <Textarea
          id="jd"
          rows={12}
          value={text}
          onChange={(e) => onText(e.target.value)}
          placeholder="Paste the job description here…"
          data-testid="jd-text"
          className={cn(drag && 'border-ink bg-ink-soft')}
        />
      )}
      <div className="mt-3">
        <Button onClick={() => ref.current?.click()}>
          <Upload className="size-4" /> {file ? 'Choose a different file' : 'Upload a file instead'}
        </Button>
        <input
          ref={ref}
          type="file"
          hidden
          accept=".pdf,.docx,.doc,.txt"
          data-testid="jd-file"
          onChange={(e) => {
            onFile(e.target.files?.[0] ?? null)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}

function Group({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div>
      <Label hint={hint}>{label}</Label>
      {children}
    </div>
  )
}

function CandidateRow({
  cv,
  req,
  weights,
  checked,
  onCheck,
  onOpen,
  explanation,
  onExplain,
}: {
  cv: RankedCV
  req: Requirements
  weights: ShortlistResult['weights']
  checked: boolean
  onCheck: (on: boolean) => void
  onOpen: () => void
  explanation?: Explanation | 'loading' | string
  onExplain?: () => void
}) {
  const [details, setDetails] = useState(false)
  const name = displayName(cv)
  const ml = matchLabel(cv.score)
  return (
    <li
      className={cn('rounded-[12px] border bg-surface p-4 shadow-e1 transition-colors md:p-5', checked ? 'border-ink' : 'border-line')}
      data-testid="shortlist-row"
    >
      <div className="flex gap-4">
        <div className="flex flex-col items-center gap-2 pt-1">
          <input type="checkbox" checked={checked} onChange={(e) => onCheck(e.target.checked)} aria-label={`Select ${name}`} className="size-4 accent-[var(--ink)]" />
          <span className="text-[12px] text-muted tabular-nums">#{cv.rank}</span>
        </div>
        <Avatar name={name} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <button type="button" onClick={onOpen} className="text-left text-[16px] font-semibold hover:underline hover:underline-offset-4">
                  {name}
                </button>
                <SourceBadges cv={cv} />
              </div>
              <p className="truncate text-[14px] text-muted">{cv.title || 'Job title not found'}</p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span
                className={cn(
                  'rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold',
                  ml.tone === 'excellent' && 'bg-ok-soft text-ok',
                  ml.tone === 'strong' && 'bg-ink-soft text-ink-strong',
                  ml.tone === 'fair' && 'bg-mark-soft text-text',
                  ml.tone === 'weak' && 'bg-sunken text-muted',
                )}
                data-testid="match-label"
              >
                {ml.label}
              </span>
              <ScoreBar score={cv.score} breakdown={cv.breakdown} weights={weights} />
            </div>
          </div>
          <p className="mt-2 text-[13.5px]" data-testid="match-reason">
            {matchReason(cv, req)}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {cv.matched_must.map((s) => (
              <Chip key={`m-${s}`} tone="mark" title="Must-have: found">
                {s}
              </Chip>
            ))}
            {cv.matched_nice.map((s) => (
              <Chip key={`n-${s}`} tone="ink" title="Nice-to-have: found">
                {s}
              </Chip>
            ))}
            {cv.missing_must.map((s) => (
              <Chip key={`x-${s}`} tone="missing" title="Must-have: not found">
                {s}
              </Chip>
            ))}
          </div>
          {cv.other_files && cv.other_files.length > 0 && (
            <p className="mt-2 text-[12px] text-muted">Also in your library as: {cv.other_files.map((f) => f.filename).join(', ')}</p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={() => setDetails((d) => !d)} aria-expanded={details}>
              <ChevronDown className={cn('size-4 transition-transform', details && 'rotate-180')} /> Score details
            </Button>
            {onExplain && !explanation && (
              <Button size="sm" variant="ghost" onClick={onExplain}>
                <Sparkles className="size-4" /> Why this score?
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onOpen}>
              View resume
            </Button>
          </div>

          {details && (
            <dl className="mt-3 grid gap-x-6 gap-y-2 rounded-md bg-sunken p-3 text-[13px] sm:grid-cols-2">
              {SEGMENTS.map((s) => (
                <div key={s.key} className="flex items-center gap-2">
                  <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} />
                  <dt className="flex-1">
                    {s.label} <HelpDot>{SEG_HELP[s.key]}</HelpDot>
                  </dt>
                  <dd className="tabular-nums">
                    {cv.breakdown[s.key].toFixed(0)} <span className="text-muted">/ {weights[s.key]}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {explanation && (
            <div className="mt-3 rounded-md border-l-2 border-ink bg-sunken/60 p-3 text-[13.5px]" data-testid="explanation" aria-live="polite">
              {explanation === 'loading' ? (
                <span className="flex items-center gap-2 text-muted">
                  <Spinner /> Smart reading is reading the resume…
                </span>
              ) : typeof explanation === 'string' ? (
                <span className="text-danger">{explanation}</span>
              ) : (
                <>
                  <p>{explanation.reason}</p>
                  {explanation.strengths.length > 0 && (
                    <p className="mt-1.5">
                      <span className="font-semibold text-ok">Strengths: </span>
                      {explanation.strengths.join('; ')}
                    </p>
                  )}
                  {explanation.gaps.length > 0 && (
                    <p className="mt-1 text-muted">
                      <span className="font-semibold">Gaps: </span>
                      {explanation.gaps.join('; ')}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
