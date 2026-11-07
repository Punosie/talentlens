import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, FileText, ListChecks, Save, Sparkles, Upload, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { CVDrawer } from '../components/CVDrawer'
import { FacetPicker } from '../components/FacetPicker'
import { ScoreBar, ScoreLegend } from '../components/ScoreBar'
import { Button, Chip, Empty, Input, Label, Spinner, Textarea, useToast } from '../components/ui'
import { api, type RankedCV, type Requirements, type ShortlistResult } from '../lib/api'
import { cn, displayName, downloadBlob, years } from '../lib/utils'

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

export default function ShortlistPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [jdInput, setJdInput] = useSessionState('sl-input', '')
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [jdText, setJdText] = useSessionState('sl-jd', '')
  const [req, setReq] = useSessionState<Requirements | null>('sl-req', null)
  const [dirty, setDirty] = useState(false)
  const [aiReq, setAiReq] = useState<Requirements | null>(null)
  const [result, setResult] = useSessionState<ShortlistResult | null>('sl-result', null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [openId, setOpenId] = useState<number | null>(null)
  const [explanations, setExplanations] = useState<Record<number, Explanation | 'loading' | string>>({})
  const [saveName, setSaveName] = useState<string | null>(null)

  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const llmOk = !!health.data?.llm.available

  const rank = useMutation({
    mutationFn: ({ r, jd }: { r: Requirements; jd: string }) => api.shortlist(r, jd, 100),
    onSuccess: (r) => {
      setResult(r)
      setSelected(new Set())
      setExplanations({})
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  // A ref, so the async AI callback sees the current value rather than a stale closure
  const dirtyRef = useRef(false)
  const markDirty = (v: boolean) => {
    dirtyRef.current = v
    setDirty(v)
  }

  const aiParse = useMutation({
    mutationFn: (input: { text?: string; file?: File }) => api.parseJd({ ...input, mode: 'ai' }),
    onSuccess: (r) => {
      if (r.warning) return toast(r.warning)
      if (dirtyRef.current) {
        setAiReq(r.requirements) // user edited meanwhile: offer, don't overwrite
        return
      }
      setReq(r.requirements)
      rank.mutate({ r: r.requirements, jd: r.jd_text })
      toast('Requirements refined by local AI and results updated', 'ok')
    },
    onError: () => toast('Local AI could not read this JD; using the rule-based requirements.'),
  })

  const parse = useMutation({
    mutationFn: (input: { text?: string; file?: File }) => api.parseJd({ ...input, mode: 'rules' }),
    onSuccess: (r, input) => {
      setJdText(r.jd_text)
      setReq(r.requirements)
      markDirty(false)
      setAiReq(null)
      setResult(null)
      rank.mutate({ r: r.requirements, jd: r.jd_text })
      if (llmOk) aiParse.mutate(input)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const edit = (patch: Partial<Requirements>) => {
    setReq((r) => ({ ...(r ?? EMPTY_REQ), ...patch, source: 'user' }))
    markDirty(true)
  }

  const start = () => {
    if (jdFile) parse.mutate({ file: jdFile })
    else if (jdInput.trim().length >= 20) parse.mutate({ text: jdInput })
    else toast('Paste the job description or choose a file first', 'error')
  }

  const explain = async (cv: RankedCV) => {
    if (!req) return
    setExplanations((e) => ({ ...e, [cv.id]: 'loading' }))
    try {
      const r = await api.explain(cv.id, req)
      setExplanations((e) => ({ ...e, [cv.id]: r }))
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
      setSaveName(null)
      navigate(`/saved/${r.id}`)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const exportCsv = async () => {
    if (!req) return
    const name = `${req.title || 'shortlist'}`.slice(0, 60)
    try {
      const blob = await api.exportUnsaved({ name, jd_text: jdText, requirements: req, results: chosen })
      downloadBlob(blob, `${name}.csv`)
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
    markDirty(false)
  }

  const skillOptions = facets.data?.skills ?? []
  const locationOptions = [
    ...(facets.data?.countries ?? []).map((c) => ({ value: c.value, count: c.count, hint: 'country' })),
    ...(facets.data?.cities ?? []).map((c) => ({ value: c.value, count: c.count, hint: c.country })),
  ]

  // ---------------- step 1: JD input ----------------
  if (!req) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
        <h1 className="text-2xl font-bold tracking-tight">Shortlist for a job</h1>
        <p className="mt-1 text-sm text-muted">
          Paste a job description or upload it as PDF, Word or text. TalentLens pulls out the requirements, which you
          can adjust, and ranks every resume against them.
        </p>
        <div className="mt-6">
          <Label htmlFor="jd">Job description</Label>
          <Textarea
            id="jd"
            rows={12}
            value={jdInput}
            disabled={!!jdFile}
            onChange={(e) => setJdInput(e.target.value)}
            placeholder="Paste the full job description here…"
            data-testid="jd-text"
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={() => fileRef.current?.click()}>
            <Upload className="size-4" /> {jdFile ? 'Choose another file' : 'Upload JD file'}
          </Button>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".pdf,.docx,.doc,.txt"
            data-testid="jd-file"
            onChange={(e) => {
              setJdFile(e.target.files?.[0] ?? null)
              e.target.value = ''
            }}
          />
          {jdFile && (
            <Chip tone="ink" onRemove={() => setJdFile(null)}>
              <FileText className="mr-1 inline size-3.5" />
              {jdFile.name}
            </Chip>
          )}
          <div className="flex-1" />
          <Button variant="primary" onClick={start} busy={parse.isPending} data-testid="jd-submit">
            <ListChecks className="size-4" /> Find candidates
          </Button>
        </div>
        <p className="mt-4 text-[13px] text-muted">
          {llmOk
            ? 'Rule-based requirements appear instantly. The local AI then refines them in about a minute.'
            : 'Local AI is offline, so requirements are extracted with rules. You can still edit them.'}
        </p>
      </div>
    )
  }

  // ---------------- step 2: requirements + results ----------------
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold tracking-tight">{req.title || 'Shortlist'}</h1>
          <p className="text-sm text-muted">
            {req.source === 'llm' ? 'Requirements read by local AI' : req.source === 'rules' ? 'Requirements read by rules' : 'Requirements edited by you'}
            {aiParse.isPending && (
              <span className="ml-2 inline-flex items-center gap-1.5" data-testid="ai-refining">
                <Sparkles className="size-3.5" /> AI is refining the requirements…
              </span>
            )}
          </p>
        </div>
        <Button variant="ghost" onClick={reset}>
          <X className="size-4" /> New job description
        </Button>
      </div>

      {aiReq && dirty && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-l-2 border-mark bg-mark-soft px-4 py-3 text-sm">
          <Sparkles className="size-4" /> The local AI has suggested requirements. Your edits were kept.
          <Button
            size="sm"
            onClick={() => {
              setReq(aiReq)
              setAiReq(null)
              markDirty(false)
              rank.mutate({ r: aiReq, jd: jdText })
            }}
          >
            Use AI version
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAiReq(null)}>
            Dismiss
          </Button>
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-8 xl:grid-cols-[320px_minmax(0,1fr)]">
        {/* requirements editor */}
        <aside className="order-2 space-y-5 xl:order-1" aria-label="Requirements" data-testid="requirements">
          <div>
            <Label htmlFor="req-title">Role</Label>
            <Input id="req-title" value={req.title ?? ''} onChange={(e) => edit({ title: e.target.value || null })} />
          </div>
          <Field label="Must-have skills">
            <FacetPicker
              label="Must-have skills"
              testId="req-must"
              options={skillOptions}
              selected={req.must_have_skills}
              onChange={(v) => edit({ must_have_skills: v })}
              allowCustom
            />
          </Field>
          <Field label="Nice-to-have skills">
            <FacetPicker
              label="Nice-to-have skills"
              testId="req-nice"
              options={skillOptions}
              selected={req.nice_to_have_skills}
              onChange={(v) => edit({ nice_to_have_skills: v })}
              allowCustom
            />
          </Field>
          <Field label="Years of experience">
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                max={50}
                placeholder="Min"
                aria-label="Minimum years required"
                className="h-9"
                value={req.min_years ?? ''}
                onChange={(e) => edit({ min_years: e.target.value === '' ? null : Number(e.target.value) })}
              />
              <span className="text-muted">to</span>
              <Input
                type="number"
                min={0}
                max={50}
                placeholder="Max"
                aria-label="Maximum years"
                className="h-9"
                value={req.max_years ?? ''}
                onChange={(e) => edit({ max_years: e.target.value === '' ? null : Number(e.target.value) })}
              />
            </div>
          </Field>
          <Field label="Location">
            <FacetPicker
              label="Location"
              testId="req-location"
              options={locationOptions}
              selected={req.locations}
              onChange={(v) => edit({ locations: v })}
              allowCustom
            />
          </Field>
          <Field label="Industry">
            <FacetPicker
              label="Industry"
              testId="req-domain"
              options={facets.data?.domains ?? []}
              selected={req.domains}
              onChange={(v) => edit({ domains: v })}
            />
          </Field>
          {dirty && (
            <Button variant="primary" className="w-full" onClick={() => rank.mutate({ r: req, jd: jdText })} busy={rank.isPending} data-testid="rerank">
              Update results
            </Button>
          )}
          <details className="text-sm">
            <summary className="cursor-pointer text-muted">Job description text</summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-sunken p-3 font-sans text-[12.5px] whitespace-pre-wrap">
              {jdText}
            </pre>
          </details>
        </aside>

        {/* results (first on small screens) */}
        <section className="order-1 min-w-0 xl:order-2">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
            <div>
              <p className="text-sm font-medium" data-testid="shortlist-count">
                {rank.isPending
                  ? 'Ranking resumes…'
                  : result
                    ? `${result.total} candidates ranked${selected.size ? ` · ${selected.size} selected` : ''}`
                    : ''}
              </p>
              <div className="mt-1">
                <ScoreLegend weights={result?.weights} />
              </div>
            </div>
            {result && result.items.length > 0 && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={exportCsv} data-testid="export-csv">
                  <Download className="size-4" /> Export CSV{selected.size ? ` (${selected.size})` : ''}
                </Button>
                {saveName === null ? (
                  <Button size="sm" variant="primary" onClick={() => setSaveName(req.title || 'Shortlist')} data-testid="save-open">
                    <Save className="size-4" /> Save{selected.size ? ` ${selected.size}` : ''}
                  </Button>
                ) : (
                  <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault()
                      if (saveName.trim()) save.mutate(saveName.trim())
                    }}
                  >
                    <Input
                      autoFocus
                      value={saveName}
                      onChange={(e) => setSaveName(e.target.value)}
                      className="h-8 w-56"
                      aria-label="Shortlist name"
                      data-testid="save-name"
                    />
                    <Button size="sm" variant="primary" type="submit" busy={save.isPending} data-testid="save-confirm">
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" type="button" onClick={() => setSaveName(null)}>
                      Cancel
                    </Button>
                  </form>
                )}
              </div>
            )}
          </div>

          {rank.isPending && !result && (
            <div className="flex items-center gap-2 py-10 text-sm text-muted">
              <Spinner /> Comparing every resume with the requirements (about 10 seconds)…
            </div>
          )}
          {result && result.items.length === 0 && (
            <div className="mt-6">
              <Empty title="No candidates found">Loosen the must-have skills or remove the location.</Empty>
            </div>
          )}

          <ol className={cn('divide-y divide-line', rank.isPending && 'opacity-60')} data-testid="shortlist-results">
            {result?.items.map((cv) => (
              <ResultRow
                key={cv.id}
                cv={cv}
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
        </section>
      </div>

      <CVDrawer
        cvId={openId}
        onClose={() => setOpenId(null)}
        highlight={[...(req.must_have_skills ?? []), ...(req.nice_to_have_skills ?? [])]}
      />
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function ResultRow({
  cv,
  weights,
  checked,
  onCheck,
  onOpen,
  explanation,
  onExplain,
}: {
  cv: RankedCV
  weights: ShortlistResult['weights']
  checked: boolean
  onCheck: (on: boolean) => void
  onOpen: () => void
  explanation?: Explanation | 'loading' | string
  onExplain?: () => void
}) {
  return (
    <li className="py-4" data-testid="shortlist-row">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 md:grid-cols-[auto_minmax(0,1fr)_auto]">
        <div className="flex items-start gap-3 pt-1">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onCheck(e.target.checked)}
            aria-label={`Select ${displayName(cv)}`}
            className="mt-1 size-4 accent-[var(--ink)]"
          />
          <span className="w-6 text-right text-sm text-muted tabular-nums">{cv.rank}</span>
        </div>
        <div className="min-w-0">
          <button type="button" onClick={onOpen} className="text-left">
            <span className="text-[16px] font-semibold hover:underline hover:underline-offset-4">{displayName(cv)}</span>
          </button>
          <p className="truncate text-sm text-muted">
            {[cv.title, years(cv.years_exp), cv.location].filter(Boolean).join(' · ')}
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
            <p className="mt-1.5 text-[12px] text-muted">
              Also on file: {cv.other_files.map((f) => f.filename).join(', ')}
            </p>
          )}
          {explanation && (
            <div className="mt-3 border-l-2 border-ink pl-3 text-sm" data-testid="explanation">
              {explanation === 'loading' ? (
                <span className="flex items-center gap-2 text-muted">
                  <Spinner /> The local AI is reading the resume (up to a minute)…
                </span>
              ) : typeof explanation === 'string' ? (
                <span className="text-danger">{explanation}</span>
              ) : (
                <>
                  <p>{explanation.reason}</p>
                  {explanation.strengths.length > 0 && (
                    <p className="mt-1 text-[13px]">
                      <span className="font-semibold">Strengths: </span>
                      {explanation.strengths.join('; ')}
                    </p>
                  )}
                  {explanation.gaps.length > 0 && (
                    <p className="mt-1 text-[13px] text-muted">
                      <span className="font-semibold">Gaps: </span>
                      {explanation.gaps.join('; ')}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        <div className="col-start-2 flex items-center gap-3 md:col-start-auto md:flex-col md:items-end">
          <ScoreBar score={cv.score} breakdown={cv.breakdown} weights={weights} />
          {onExplain && !explanation && (
            <Button size="sm" variant="ghost" onClick={onExplain}>
              <Sparkles className="size-4" /> Why this score?
            </Button>
          )}
        </div>
      </div>
    </li>
  )
}
