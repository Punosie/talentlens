import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { FileUp, Inbox, MapPin, Search, SlidersHorizontal, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { CVDrawer } from '../components/CVDrawer'
import { FacetPicker } from '../components/FacetPicker'
import { Button, Chip, Empty, Input, Label, Spinner } from '../components/ui'
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

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function LibraryPage() {
  const [sp, setSp] = useSearchParams()
  const [text, setText] = useState(sp.get('q') ?? '')
  const q = useDebounced(text, 300)
  const [openId, setOpenId] = useState<number | null>(null)
  const [showFilters, setShowFilters] = useState(false)

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

  const setList = (key: string, values: string[]) => {
    const next = new URLSearchParams(sp)
    next.delete(key)
    values.forEach((v) => next.append(key, v))
    setSp(next, { replace: true })
  }
  const setOne = (key: string, value: string | null) => {
    const next = new URLSearchParams(sp)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setSp(next, { replace: true })
  }

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
  const activeFilters =
    params.skills!.length + params.location!.length + params.domain!.length +
    (params.years_min !== null || params.years_max !== null ? 1 : 0)

  const locationOptions = useMemo(() => {
    const f = facets.data
    if (!f) return []
    return [
      ...f.countries.map((c) => ({ value: c.value, count: c.count, hint: 'country' })),
      ...f.cities.map((c) => ({ value: c.value, count: c.count, hint: c.country })),
    ]
  }, [facets.data])

  const filters = (
    <div className="space-y-6">
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <Label>Skills</Label>
          {params.skills!.length > 1 && (
            <div className="flex rounded border border-line-strong text-[12px]" role="group" aria-label="Skill match mode">
              {(['all', 'any'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setOne('mode', m === 'all' ? null : m)}
                  className={cn('px-2 py-0.5', params.skills_mode === m ? 'bg-ink text-on-ink' : 'text-muted')}
                  aria-pressed={params.skills_mode === m}
                >
                  {m === 'all' ? 'Match all' : 'Match any'}
                </button>
              ))}
            </div>
          )}
        </div>
        <FacetPicker
          label="Skills"
          testId="filter-skills"
          options={facets.data?.skills ?? []}
          selected={params.skills!}
          onChange={(v) => setList('skill', v)}
        />
      </div>

      <div>
        <Label>Years of experience</Label>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={0}
            max={60}
            inputMode="numeric"
            placeholder="Min"
            aria-label="Minimum years"
            data-testid="filter-years-min"
            value={sp.get('ymin') ?? ''}
            onChange={(e) => setOne('ymin', e.target.value)}
            className="h-9"
          />
          <span className="text-muted">to</span>
          <Input
            type="number"
            min={0}
            max={60}
            inputMode="numeric"
            placeholder="Max"
            aria-label="Maximum years"
            data-testid="filter-years-max"
            value={sp.get('ymax') ?? ''}
            onChange={(e) => setOne('ymax', e.target.value)}
            className="h-9"
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {YEAR_PRESETS.map(([label, lo, hi]) => {
            const n = facets.data?.years.buckets[label.replace('–', '-')]
            const on = params.years_min === lo && params.years_max === hi
            return (
              <button
                key={label}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(sp)
                  if (on) {
                    next.delete('ymin')
                    next.delete('ymax')
                  } else {
                    if (lo === null) next.delete('ymin')
                    else next.set('ymin', String(lo))
                    if (hi === null) next.delete('ymax')
                    else next.set('ymax', String(hi))
                  }
                  setSp(next, { replace: true })
                }}
                className={cn(
                  'rounded border px-2 py-0.5 text-[12px] tabular-nums',
                  on ? 'border-ink bg-ink text-on-ink' : 'border-line-strong text-muted hover:text-text',
                )}
              >
                {label}
                {n !== undefined && <span className="ml-1 opacity-70">{n}</span>}
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <Label>Location</Label>
        <FacetPicker
          label="Location"
          testId="filter-location"
          options={locationOptions}
          selected={params.location!}
          onChange={(v) => setList('loc', v)}
          placeholder="Country or city…"
        />
      </div>

      <div>
        <Label>Industry</Label>
        <FacetPicker
          label="Industry"
          testId="filter-domain"
          options={facets.data?.domains ?? []}
          selected={params.domain!}
          onChange={(v) => setList('dom', v)}
        />
      </div>

      {activeFilters > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const next = new URLSearchParams()
            if (q) next.set('q', q)
            setSp(next, { replace: true })
          }}
        >
          <X className="size-4" /> Clear filters
        </Button>
      )}
    </div>
  )

  return (
    <div className="mx-auto flex max-w-[1400px] gap-8 px-4 py-6 md:px-8">
      <aside
        className={cn(
          'w-64 shrink-0',
          showFilters ? 'fixed inset-0 z-30 block w-full overflow-y-auto bg-paper p-6' : 'hidden lg:block',
        )}
        aria-label="Filters"
      >
        <div className="sticky top-0 lg:pt-1">
          {showFilters && (
            <div className="mb-4 flex justify-between lg:hidden">
              <span className="font-semibold">Filters</span>
              <Button size="sm" onClick={() => setShowFilters(false)}>
                Show {total} results
              </Button>
            </div>
          )}
          {filters}
        </div>
      </aside>

      <section className="min-w-0 flex-1">
        <h1 className="sr-only">Resume library</h1>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted" />
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search by role, skill, company, anything in the resume…"
              className="h-12 pl-11 text-[15px]"
              aria-label="Search resumes"
              data-testid="search-input"
              type="search"
            />
          </div>
          <Button className="h-12 lg:hidden" onClick={() => setShowFilters(true)} aria-label="Filters">
            <SlidersHorizontal className="size-4" />
            {activeFilters > 0 && <span className="tabular-nums">{activeFilters}</span>}
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <p className="text-sm text-muted" data-testid="result-count">
            {results.isLoading ? 'Searching…' : `${total} resume${total === 1 ? '' : 's'}`}
            {q && !results.isLoading && <> for “{q}”</>}
          </p>
          <label className="flex items-center gap-2 text-sm text-muted">
            Sort
            <select
              value={params.sort}
              onChange={(e) => setOne('sort', e.target.value)}
              className="h-8 rounded border border-line-strong bg-surface px-2 text-sm text-text"
              data-testid="sort-select"
            >
              {q && <option value="relevance">Best match</option>}
              <option value="recent">Recently added</option>
              <option value="experience">Most experience</option>
              <option value="name">Name</option>
            </select>
          </label>
        </div>

        {results.error && <p className="mt-6 text-sm text-danger">{(results.error as Error).message}</p>}

        {!results.isLoading && items.length === 0 && (
          <div className="mt-8">
            {total === 0 && !q && activeFilters === 0 ? (
              <Empty icon={<Inbox className="size-6" />} title="No resumes indexed yet">
                Add resumes, or click Refresh at the top right if files are already in the folder.{' '}
                <Link to="/upload" className="font-medium text-ink underline">
                  Add resumes
                </Link>
              </Empty>
            ) : (
              <Empty title="Nothing matches">Try fewer filters, “Match any” for skills, or a broader search.</Empty>
            )}
          </div>
        )}

        <ul className="divide-y divide-line" data-testid="results">
          {items.map((cv) => (
            <ResultRow key={cv.id} cv={cv} selectedSkills={params.skills!} onOpen={() => setOpenId(cv.id)} />
          ))}
        </ul>

        {results.hasNextPage && (
          <div className="py-6">
            <Button onClick={() => results.fetchNextPage()} busy={results.isFetchingNextPage}>
              Show more
            </Button>
          </div>
        )}
        {results.isLoading && (
          <div className="py-8">
            <Spinner />
          </div>
        )}
      </section>

      <CVDrawer cvId={openId} onClose={() => setOpenId(null)} highlight={params.skills} />
      <Link
        to="/upload"
        className="fixed right-6 bottom-6 flex h-12 items-center gap-2 rounded-full bg-ink px-5 text-sm font-medium text-on-ink shadow-lg hover:bg-ink-strong md:hidden"
      >
        <FileUp className="size-4" /> Add
      </Link>
    </div>
  )
}

function ResultRow({ cv, selectedSkills, onOpen }: { cv: CVSummary; selectedSkills: string[]; onOpen: () => void }) {
  const want = new Set(selectedSkills.map((s) => s.toLowerCase()))
  const matched = cv.skills.filter((s) => want.has(s.toLowerCase()))
  const rest = cv.skills.filter((s) => !want.has(s.toLowerCase()))
  const shown = [...matched, ...rest].slice(0, 9)
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="group grid w-full grid-cols-1 gap-x-6 gap-y-1 py-4 text-left hover:bg-surface md:grid-cols-[minmax(0,1fr)_200px] md:px-3"
        data-testid="result-row"
      >
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-[16px] font-semibold group-hover:underline group-hover:decoration-line-strong group-hover:underline-offset-4">
              {displayName(cv)}
            </span>
            {cv.status !== 'indexed' && <Chip tone="missing">unreadable</Chip>}
          </div>
          <p className="truncate text-sm text-muted">{cv.title || cv.filename}</p>
          {cv.snippet && (
            <p className="mt-1.5 line-clamp-2 text-[13px] text-muted">
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
          <div className="mt-2 flex flex-wrap gap-1.5">
            {shown.map((s) => (
              <Chip key={s} tone={want.has(s.toLowerCase()) ? 'mark' : 'plain'}>
                {s}
              </Chip>
            ))}
            {cv.skills.length > shown.length && (
              <span className="px-1 text-[12px] text-muted">+{cv.skills.length - shown.length}</span>
            )}
          </div>
        </div>
        <div className="flex flex-row flex-wrap gap-x-4 text-sm md:flex-col md:items-end md:text-right">
          <span className="font-semibold tabular-nums">{years(cv.years_exp)}</span>
          <span className="flex items-center gap-1 text-muted">
            <MapPin className="size-3.5" />
            {cv.location || 'Location not found'}
          </span>
          {cv.domains[0] && <span className="text-[12px] text-muted">{cv.domains.slice(0, 2).join(' · ')}</span>}
        </div>
      </button>
    </li>
  )
}
