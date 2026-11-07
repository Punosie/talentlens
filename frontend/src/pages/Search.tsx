import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Briefcase, FileUp, Inbox, MapPin, Search as SearchIcon, SlidersHorizontal, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { CandidateProfile } from '../components/CandidateProfile'
import { FacetPicker } from '../components/FacetPicker'
import { Avatar, Button, Chip, Empty, HelpDot, Input, Kbd, Label, Skeleton } from '../components/ui'
import { api, type CVSummary, type SearchParams } from '../lib/api'
import { cn, displayName, snippetParts, years } from '../lib/utils'

const PAGE = 30
const YEAR_PRESETS: [string, number | null, number | null][] = [
  ['0–3', 0, 3],
  ['3–6', 3, 6],
  ['6–10', 6, 10],
  ['10–15', 10, 15],
  ['15+', 15, null],
]
const EXAMPLES = ['Python developer', 'retail store manager', 'telecom churn', 'SAP finance']

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function SearchPage() {
  const [sp, setSp] = useSearchParams()
  const [text, setText] = useState(sp.get('q') ?? '')
  const q = useDebounced(text, 300)
  const [openId, setOpenId] = useState<number | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // "/" focuses the search box, like Gmail / GitHub
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) && !t.isContentEditable) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const params: SearchParams = useMemo(
    () => ({
      q: q || undefined,
      skills: sp.getAll('skill'),
      skills_mode: (sp.get('mode') as 'all' | 'any') || 'all',
      years_min: sp.get('ymin') ? Number(sp.get('ymin')) : null,
      years_max: sp.get('ymax') ? Number(sp.get('ymax')) : null,
      location: sp.getAll('loc'),
      domain: sp.getAll('dom'),
      sort: (sp.get('sort') as SearchParams['sort']) || (q ? 'relevance' : 'recent'),
    }),
    [q, sp],
  )

  useEffect(() => {
    const next = new URLSearchParams(sp)
    if (q) next.set('q', q)
    else next.delete('q')
    if (next.toString() !== sp.toString()) setSp(next, { replace: true })
  }, [q, sp, setSp])

  // Always build on the *latest* URL state: quick successive edits (e.g. min then max years)
  // must not start from a stale snapshot and drop each other.
  const update = (fn: (n: URLSearchParams) => void) =>
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev)
        fn(next)
        return next
      },
      { replace: true },
    )
  const setList = (key: string, values: string[]) =>
    update((n) => {
      n.delete(key)
      values.forEach((v) => n.append(key, v))
    })
  const setOne = (key: string, value: string | null) => update((n) => (value ? n.set(key, value) : n.delete(key)))
  const removeOne = (key: string, value: string) =>
    update((n) => {
      const keep = n.getAll(key).filter((v) => v !== value)
      n.delete(key)
      keep.forEach((v) => n.append(key, v))
    })

  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const results = useInfiniteQuery({
    queryKey: ['search', params],
    queryFn: ({ pageParam }) => api.search({ ...params, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const items = results.data?.pages.flatMap((p) => p.items) ?? []
  const total = results.data?.pages[0]?.total ?? 0

  const yearsActive = params.years_min !== null || params.years_max !== null
  const activeCount = params.skills!.length + params.location!.length + params.domain!.length + (yearsActive ? 1 : 0)
  const yearLabel =
    params.years_min !== null && params.years_max !== null
      ? `${params.years_min}–${params.years_max} yrs`
      : params.years_min !== null
        ? `${params.years_min}+ yrs`
        : `Up to ${params.years_max} yrs`

  const locationOptions = useMemo(() => {
    const f = facets.data
    if (!f) return []
    return [
      ...f.countries.map((c) => ({ value: c.value, count: c.count, hint: 'country' })),
      ...f.cities.map((c) => ({ value: c.value, count: c.count, hint: c.country })),
    ]
  }, [facets.data])

  const clearAll = () => update((n) => ['skill', 'mode', 'ymin', 'ymax', 'loc', 'dom'].forEach((k) => n.delete(k)))

  const filters = (
    <div className="space-y-7">
      <div>
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold">
            Skills
            <HelpDot>Pick skills from your library. With several skills, choose whether a person needs all of them or any one.</HelpDot>
          </span>
          {params.skills!.length > 1 && (
            <div className="flex rounded-md border border-line-strong text-[12px]" role="group" aria-label="Skill match mode">
              {(['all', 'any'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setOne('mode', m === 'all' ? null : m)}
                  className={cn('px-2 py-0.5 first:rounded-l-md last:rounded-r-md', params.skills_mode === m ? 'bg-ink text-on-ink' : 'text-muted')}
                  aria-pressed={params.skills_mode === m}
                >
                  {m === 'all' ? 'Match all' : 'Match any'}
                </button>
              ))}
            </div>
          )}
        </div>
        <FacetPicker label="Skills" testId="filter-skills" options={facets.data?.skills ?? []} selected={params.skills!} onChange={(v) => setList('skill', v)} />
      </div>

      <div>
        <Label>Years of experience</Label>
        <div className="flex flex-wrap gap-1.5">
          {YEAR_PRESETS.map(([label, lo, hi]) => {
            const n = facets.data?.years.buckets[label.replace('–', '-')]
            const on = params.years_min === lo && params.years_max === hi
            return (
              <button
                key={label}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  update((next) => {
                    next.delete('ymin')
                    next.delete('ymax')
                    if (!on) {
                      if (lo !== null) next.set('ymin', String(lo))
                      if (hi !== null) next.set('ymax', String(hi))
                    }
                  })
                }
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[12.5px] tabular-nums transition-colors',
                  on ? 'border-ink bg-ink text-on-ink' : 'border-line-strong text-muted hover:border-ink hover:text-text',
                )}
              >
                {label} yrs{n !== undefined && <span className="ml-1 opacity-70">({n})</span>}
              </button>
            )
          })}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <Input type="number" min={0} max={60} inputMode="numeric" placeholder="Min" aria-label="Minimum years" data-testid="filter-years-min" value={sp.get('ymin') ?? ''} onChange={(e) => setOne('ymin', e.target.value)} className="h-9" />
          <span className="text-[13px] text-muted">to</span>
          <Input type="number" min={0} max={60} inputMode="numeric" placeholder="Max" aria-label="Maximum years" data-testid="filter-years-max" value={sp.get('ymax') ?? ''} onChange={(e) => setOne('ymax', e.target.value)} className="h-9" />
        </div>
      </div>

      <div>
        <Label>Location</Label>
        <FacetPicker label="Location" testId="filter-location" options={locationOptions} selected={params.location!} onChange={(v) => setList('loc', v)} placeholder="Country or city…" />
      </div>

      <div>
        <Label>Industry</Label>
        <FacetPicker label="Industry" testId="filter-domain" options={facets.data?.domains ?? []} selected={params.domain!} onChange={(v) => setList('dom', v)} />
      </div>
    </div>
  )

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight md:text-[28px]">Search resumes</h1>
        <p className="mt-1 text-[15px] text-muted">Type anything (a role, a skill, a company) and narrow it down with filters.</p>
      </div>

      <div className="flex gap-8">
        <aside
          className={cn('w-64 shrink-0', showFilters ? 'fixed inset-0 z-30 block w-full overflow-y-auto bg-paper p-6' : 'hidden lg:block')}
          aria-label="Filters"
        >
          <div className="lg:sticky lg:top-2">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Filters</h2>
              {showFilters ? (
                <Button size="sm" variant="primary" onClick={() => setShowFilters(false)}>
                  Show {total} results
                </Button>
              ) : (
                activeCount > 0 && (
                  <button type="button" onClick={clearAll} className="text-[13px] font-medium text-ink hover:underline">
                    Clear all
                  </button>
                )
              )}
            </div>
            {filters}
          </div>
        </aside>

        <section className="min-w-0 flex-1">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted" />
              <Input
                ref={inputRef}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Search by role, skill, company or anything in the resume"
                className="h-12 rounded-[10px] pr-20 pl-12 text-[15px] shadow-e1"
                aria-label="Search resumes"
                data-testid="search-input"
                type="search"
              />
              {!text && (
                <span className="pointer-events-none absolute top-1/2 right-4 hidden -translate-y-1/2 md:inline">
                  <Kbd>/</Kbd>
                </span>
              )}
            </div>
            <Button className="h-12 lg:hidden" onClick={() => setShowFilters(true)} aria-label="Filters">
              <SlidersHorizontal className="size-4" />
              {activeCount > 0 && <span className="tabular-nums">{activeCount}</span>}
            </Button>
          </div>

          {!text && !activeCount && (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              Try:
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" onClick={() => setText(ex)} className="rounded-full border border-line-strong px-2.5 py-0.5 hover:border-ink hover:text-text">
                  {ex}
                </button>
              ))}
            </div>
          )}

          {activeCount > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2" data-testid="active-filters" aria-label="Active filters">
              {params.skills!.map((s) => (
                <Chip key={`s-${s}`} tone="ink" onRemove={() => removeOne('skill', s)}>
                  {s}
                </Chip>
              ))}
              {params.skills!.length > 1 && <Chip tone="outline">{params.skills_mode === 'any' ? 'any of these skills' : 'all of these skills'}</Chip>}
              {yearsActive && (
                <Chip
                  tone="ink"
                  onRemove={() =>
                    update((n) => {
                      n.delete('ymin')
                      n.delete('ymax')
                    })
                  }
                >
                  {yearLabel}
                </Chip>
              )}
              {params.location!.map((s) => (
                <Chip key={`l-${s}`} tone="ink" onRemove={() => removeOne('loc', s)}>
                  {s}
                </Chip>
              ))}
              {params.domain!.map((s) => (
                <Chip key={`d-${s}`} tone="ink" onRemove={() => removeOne('dom', s)}>
                  {s}
                </Chip>
              ))}
              <button type="button" onClick={clearAll} className="text-[13px] font-medium text-ink hover:underline" data-testid="clear-filters">
                Clear all
              </button>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
            <p className="text-sm text-muted" data-testid="result-count" aria-live="polite">
              {results.isLoading ? 'Searching…' : `${total} resume${total === 1 ? '' : 's'}`}
              {q && !results.isLoading && <> for “{q}”</>}
            </p>
            <label className="flex items-center gap-2 text-sm text-muted">
              Sort by
              <select
                value={params.sort}
                onChange={(e) => setOne('sort', e.target.value)}
                className="h-8 rounded-md border border-line-strong bg-surface px-2 text-sm text-text"
                data-testid="sort-select"
              >
                {q && <option value="relevance">Best match</option>}
                <option value="recent">Recently added</option>
                <option value="experience">Most experience</option>
                <option value="name">Name (A–Z)</option>
              </select>
            </label>
          </div>

          {results.error && <p className="mt-6 text-sm text-danger">{(results.error as Error).message}</p>}

          {!results.isLoading && items.length === 0 && (
            <div className="mt-8">
              {total === 0 && !q && activeCount === 0 ? (
                <Empty icon={<Inbox className="size-6" />} title="No resumes yet" action={<Link to="/add"><Button variant="primary"><FileUp className="size-4" /> Add resumes</Button></Link>}>
                  Add resumes, or use “Check folder for new resumes” at the top if files are already in your folder.
                </Empty>
              ) : (
                <Empty icon={<SearchIcon className="size-6" />} title="Nothing matches" action={activeCount ? <Button onClick={clearAll}>Clear filters</Button> : undefined}>
                  Try fewer filters, “Match any” for skills, or different words.
                </Empty>
              )}
            </div>
          )}

          <ul className="mt-2 space-y-2" data-testid="results">
            {results.isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <li key={i} className="flex gap-4 rounded-[10px] border border-line bg-surface p-4">
                  <Skeleton className="size-11 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-3 w-1/2" />
                    <Skeleton className="h-5 w-2/3" />
                  </div>
                </li>
              ))}
            {items.map((cv) => (
              <ResultCard key={cv.id} cv={cv} selectedSkills={params.skills!} onOpen={() => setOpenId(cv.id)} />
            ))}
          </ul>

          {results.hasNextPage && (
            <div className="py-6 text-center">
              <Button onClick={() => results.fetchNextPage()} busy={results.isFetchingNextPage}>
                Show more results
              </Button>
            </div>
          )}
        </section>
      </div>

      <CandidateProfile cvId={openId} onClose={() => setOpenId(null)} highlight={params.skills} />
    </div>
  )
}

function ResultCard({ cv, selectedSkills, onOpen }: { cv: CVSummary; selectedSkills: string[]; onOpen: () => void }) {
  const want = new Set(selectedSkills.map((s) => s.toLowerCase()))
  const matched = cv.skills.filter((s) => want.has(s.toLowerCase()))
  const rest = cv.skills.filter((s) => !want.has(s.toLowerCase()))
  const shown = [...matched, ...rest].slice(0, 8)
  const name = displayName(cv)
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="group flex w-full gap-4 rounded-[10px] border border-line bg-surface p-4 text-left shadow-e1 transition-colors hover:border-ink"
        data-testid="result-row"
      >
        <Avatar name={name} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="truncate text-[16px] font-semibold group-hover:underline group-hover:decoration-line-strong group-hover:underline-offset-4">
              {name}
            </span>
            {cv.status !== 'indexed' && <Chip tone="missing">couldn't read</Chip>}
            {cv.extractor === 'llm' && (
              <span className="inline-flex items-center gap-0.5 text-[11.5px] text-muted" title="Details checked by smart reading">
                <Sparkles className="size-3" />
              </span>
            )}
          </div>
          <p className="truncate text-[14px] text-muted">{cv.title || cv.filename}</p>
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[13px]">
            <span className="inline-flex items-center gap-1">
              <Briefcase className="size-3.5 text-muted" />
              {years(cv.years_exp)}
            </span>
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5 text-muted" />
              {cv.location || 'Location not found'}
            </span>
            {cv.domains[0] && <span className="text-muted">{cv.domains.slice(0, 2).join(' · ')}</span>}
          </p>
          {cv.snippet && (
            <p className="mt-2 line-clamp-2 text-[13px] text-muted">
              {snippetParts(cv.snippet).map((p, i) =>
                p.hit ? (
                  <mark key={i} className="mark">
                    {p.text}
                  </mark>
                ) : (
                  <span key={i}>{p.text}</span>
                ),
              )}
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {shown.map((s) => (
              <Chip key={s} tone={want.has(s.toLowerCase()) ? 'mark' : 'plain'}>
                {s}
              </Chip>
            ))}
            {cv.skills.length > shown.length && <span className="px-1 text-[12px] leading-6 text-muted">+{cv.skills.length - shown.length} more</span>}
          </div>
        </div>
      </button>
    </li>
  )
}
