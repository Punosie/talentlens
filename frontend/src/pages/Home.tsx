import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bookmark, FileUp, FolderOpen, ListChecks, Lock, MapPin, Search, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { CandidateProfile } from '../components/CandidateProfile'
import { Avatar, Card, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { displayName, timeAgo, years } from '../lib/utils'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function HomePage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const recent = useQuery({ queryKey: ['recent'], queryFn: () => api.recent(6) })
  const lists = useQuery({ queryKey: ['shortlists'], queryFn: api.shortlists })
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const total = recent.data?.total ?? 0

  const actions = [
    {
      to: '/match',
      icon: ListChecks,
      title: 'Match candidates to a job',
      text: 'Paste a job description. Get a ranked list with reasons.',
      primary: true,
      testid: 'home-match',
    },
    { to: '/search', icon: Search, title: 'Search resumes', text: 'Find people by skill, experience, place or industry.', testid: 'home-search' },
    { to: '/add', icon: FileUp, title: 'Add resumes', text: 'Upload files, a whole folder or a ZIP.', testid: 'home-add' },
  ]

  return (
    <div className="mx-auto max-w-[1180px] px-4 py-8 md:px-8 md:py-10">
      <h1 className="text-[28px] font-bold tracking-tight md:text-[32px]">{greeting()}</h1>
      <p className="mt-1 text-[15px] text-muted">
        {total ? (
          <>
            You have <b className="text-text">{total} resumes</b> in your library.
          </>
        ) : (
          'Your private resume library.'
        )}
      </p>

      <form
        className="relative mt-6 max-w-2xl"
        onSubmit={(e) => {
          e.preventDefault()
          navigate(`/search${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`)
        }}
        role="search"
      >
        <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search resumes, e.g. “Python Bengaluru” or “retail store manager”"
          aria-label="Search resumes"
          className="h-14 w-full rounded-[12px] border border-line-strong bg-surface pr-4 pl-12 text-[15px] shadow-e1 placeholder:text-muted focus:border-ink focus:outline-none"
          data-testid="home-search-input"
        />
      </form>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {actions.map(({ to, icon: Icon, title, text, primary, testid }) => (
          <Link
            key={to}
            to={to}
            data-testid={testid}
            className={
              primary
                ? 'group flex flex-col gap-3 rounded-[12px] bg-ink p-5 text-on-ink shadow-e1 transition-transform hover:-translate-y-0.5'
                : 'group flex flex-col gap-3 rounded-[12px] border border-line bg-surface p-5 shadow-e1 transition-colors hover:border-ink'
            }
          >
            <span className={primary ? 'flex size-10 items-center justify-center rounded-full bg-white/15' : 'flex size-10 items-center justify-center rounded-full bg-ink-soft text-ink'}>
              <Icon className="size-5" />
            </span>
            <span className="text-[17px] font-semibold">{title}</span>
            <span className={primary ? 'text-[14px] opacity-85' : 'text-[14px] text-muted'}>{text}</span>
            <span className="mt-auto inline-flex items-center gap-1 text-[13px] font-semibold">
              Start <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>
        ))}
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card as="section" className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[16px] font-semibold">Recently added</h2>
            <Link to="/search?sort=recent" className="text-[13px] font-medium text-ink hover:underline">
              See all
            </Link>
          </div>
          <ul className="mt-3 divide-y divide-line">
            {recent.isLoading &&
              Array.from({ length: 4 }).map((_, i) => (
                <li key={i} className="flex items-center gap-3 py-3">
                  <Skeleton className="size-9 rounded-full" />
                  <Skeleton className="h-4 w-1/2" />
                </li>
              ))}
            {recent.data?.items.map((cv) => (
              <li key={cv.id}>
                <button type="button" onClick={() => setOpenId(cv.id)} className="flex w-full items-center gap-3 py-3 text-left hover:bg-sunken/60">
                  <Avatar name={displayName(cv)} size={36} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium">{displayName(cv)}</span>
                    <span className="block truncate text-[12.5px] text-muted">
                      {[cv.title, years(cv.years_exp), cv.location].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  <span className="hidden shrink-0 text-[12px] text-muted sm:inline">{timeAgo(cv.added_at)}</span>
                </button>
              </li>
            ))}
            {recent.data && !recent.data.items.length && (
              <li className="py-6 text-sm text-muted">
                No resumes yet.{' '}
                <Link to="/add" className="font-medium text-ink underline">
                  Add your first resumes
                </Link>
              </li>
            )}
          </ul>
        </Card>

        <div className="space-y-6">
          <Card as="section" className="p-5">
            <h2 className="text-[16px] font-semibold">Your library at a glance</h2>
            {facets.data ? (
              <>
                <p className="mt-3 text-[12px] font-medium text-muted">Most common skills</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {facets.data.skills.slice(0, 8).map((s) => (
                    <Link key={s.value} to={`/search?skill=${encodeURIComponent(s.value)}`} className="rounded-[5px] bg-sunken px-1.5 py-0.5 text-[12.5px] hover:bg-ink-soft">
                      {s.value} <span className="text-muted">{s.count}</span>
                    </Link>
                  ))}
                </div>
                <p className="mt-4 text-[12px] font-medium text-muted">Top locations</p>
                <ul className="mt-1.5 space-y-1 text-[13px]">
                  {facets.data.countries.slice(0, 4).map((c) => (
                    <li key={c.value}>
                      <Link to={`/search?loc=${encodeURIComponent(c.value)}`} className="flex items-center justify-between hover:text-ink">
                        <span className="flex items-center gap-1.5">
                          <MapPin className="size-3.5 text-muted" />
                          {c.value}
                        </span>
                        <span className="text-muted tabular-nums">{c.count}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <Skeleton className="mt-3 h-24 w-full" />
            )}
          </Card>

          <Card as="section" className="p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Saved lists</h2>
              <Link to="/saved" className="text-[13px] font-medium text-ink hover:underline">
                All
              </Link>
            </div>
            <ul className="mt-2 space-y-1">
              {lists.data?.slice(0, 4).map((l) => (
                <li key={l.id}>
                  <Link to={`/saved/${l.id}`} className="flex items-center gap-2 rounded px-1 py-1.5 text-[13.5px] hover:bg-sunken">
                    <Bookmark className="size-3.5 shrink-0 text-muted" />
                    <span className="min-w-0 flex-1 truncate">{l.name}</span>
                    <span className="text-[12px] text-muted">{l.count}</span>
                  </Link>
                </li>
              ))}
              {lists.data && !lists.data.length && (
                <li className="text-[13px] text-muted">Lists you save from “Match to a job” appear here.</li>
              )}
            </ul>
          </Card>
        </div>
      </div>

      <Card as="section" className="mt-6 p-5">
        <h2 className="text-[16px] font-semibold">How TalentLens works</h2>
        <ol className="mt-4 grid gap-5 md:grid-cols-3">
          {[
            { icon: FolderOpen, t: 'It reads your resume folder', d: settings.data?.cv_dir ? `Folder: ${settings.data.cv_dir}` : 'Choose it in Settings.' },
            { icon: Sparkles, t: 'It understands each resume', d: 'Skills, experience, location and industry are picked out automatically.' },
            { icon: Lock, t: 'Everything stays here', d: 'Nothing is uploaded. The AI runs on this computer.' },
          ].map(({ icon: Icon, t, d }, i) => (
            <li key={t} className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink-soft text-[13px] font-semibold text-ink">{i + 1}</span>
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-[14px] font-semibold">
                  <Icon className="size-4 text-muted" />
                  {t}
                </p>
                <p className="mt-0.5 text-[13px] break-words text-muted">{d}</p>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <CandidateProfile cvId={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}
