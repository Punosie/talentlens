import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bookmark, Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { CVDrawer } from '../components/CVDrawer'
import { ScoreBar } from '../components/ScoreBar'
import { Button, Chip, Empty, Spinner, useToast } from '../components/ui'
import { api } from '../lib/api'
import { displayName, timeAgo, years } from '../lib/utils'

export default function SavedPage() {
  const { id } = useParams()
  return id ? <SavedDetail id={Number(id)} /> : <SavedList />
}

function SavedList() {
  const list = useQuery({ queryKey: ['shortlists'], queryFn: api.shortlists })
  return (
    <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight">Saved shortlists</h1>
      {list.isLoading && <Spinner className="mt-6" />}
      {list.data?.length === 0 && (
        <div className="mt-6">
          <Empty icon={<Bookmark className="size-6" />} title="No saved shortlists yet">
            Run a <Link to="/shortlist" className="font-medium text-ink underline">shortlist</Link> for a job and
            save the candidates you want to keep.
          </Empty>
        </div>
      )}
      <ul className="mt-6 divide-y divide-line border-y border-line" data-testid="saved-list">
        {list.data?.map((s) => (
          <li key={s.id}>
            <Link to={`/saved/${s.id}`} className="flex items-center justify-between gap-4 py-4 hover:bg-surface md:px-3">
              <div className="min-w-0">
                <p className="truncate font-semibold">{s.name}</p>
                <p className="text-sm text-muted">
                  {s.count} candidate{s.count === 1 ? '' : 's'} · saved {timeAgo(s.created_at)}
                </p>
              </div>
              <span className="text-sm text-muted">Open</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SavedDetail({ id }: { id: number }) {
  const toast = useToast()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [openId, setOpenId] = useState<number | null>(null)
  const [confirm, setConfirm] = useState(false)
  const q = useQuery({ queryKey: ['shortlist', id], queryFn: () => api.getShortlist(id) })
  const del = useMutation({
    mutationFn: () => api.deleteShortlist(id),
    onSuccess: () => {
      toast('Shortlist deleted')
      qc.invalidateQueries({ queryKey: ['shortlists'] })
      navigate('/saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (q.isLoading) return <Spinner className="m-8" />
  if (q.error || !q.data) return <p className="m-8 text-sm text-danger">{(q.error as Error)?.message ?? 'Not found'}</p>
  const s = q.data
  const highlight = [...s.requirements.must_have_skills, ...s.requirements.nice_to_have_skills]

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <Link to="/saved" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ArrowLeft className="size-4" /> All saved shortlists
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" data-testid="saved-title">
            {s.name}
          </h1>
          <p className="text-sm text-muted">
            {s.results.length} candidates · saved {timeAgo(s.created_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <a href={api.exportUrl(id)} download>
            <Button size="sm" tabIndex={-1}>
              <Download className="size-4" /> Export CSV
            </Button>
          </a>
          {confirm ? (
            <Button size="sm" variant="danger" onClick={() => del.mutate()} busy={del.isPending} data-testid="delete-confirm">
              Confirm delete
            </Button>
          ) : (
            <Button size="sm" variant="danger" onClick={() => setConfirm(true)} data-testid="delete">
              <Trash2 className="size-4" /> Delete
            </Button>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {s.requirements.must_have_skills.map((k) => (
          <Chip key={k} tone="ink">
            {k}
          </Chip>
        ))}
      </div>

      <ol className="mt-4 divide-y divide-line border-t border-line">
        {s.results.map((cv) => (
          <li key={cv.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
            <div className="min-w-0">
              <button type="button" className="text-left font-semibold hover:underline" onClick={() => setOpenId(cv.id)}>
                <span className="mr-2 text-sm font-normal text-muted tabular-nums">{cv.rank}</span>
                {displayName(cv)}
              </button>
              <p className="truncate text-sm text-muted">
                {[cv.title, years(cv.years_exp), cv.location].filter(Boolean).join(' · ')}
              </p>
            </div>
            {cv.breakdown && <ScoreBar score={cv.score} breakdown={cv.breakdown} />}
          </li>
        ))}
      </ol>
      <CVDrawer cvId={openId} onClose={() => setOpenId(null)} highlight={highlight} />
    </div>
  )
}
