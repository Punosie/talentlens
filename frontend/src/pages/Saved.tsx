import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bookmark, Download, ListChecks, Pencil, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { CandidateProfile } from '../components/CandidateProfile'
import { ScoreBar } from '../components/ScoreBar'
import { Avatar, Button, Card, Chip, ConfirmDialog, Empty, Input, Label, Modal, PageHeader, Skeleton, useToast } from '../components/ui'
import { api } from '../lib/api'
import { displayName, matchLabel, timeAgo, years } from '../lib/utils'

export default function SavedPage() {
  const { id } = useParams()
  return id ? <SavedDetail id={Number(id)} /> : <SavedList />
}

function SavedList() {
  const list = useQuery({ queryKey: ['shortlists'], queryFn: api.shortlists })
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <PageHeader
        title="Saved lists"
        description="Candidate lists you've saved from “Match to a job”."
        actions={
          <Link to="/match">
            <Button variant="primary">
              <ListChecks className="size-4" /> New match
            </Button>
          </Link>
        }
      />
      {list.isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      )}
      {list.data?.length === 0 && (
        <Empty icon={<Bookmark className="size-6" />} title="No saved lists yet" action={<Link to="/match"><Button variant="primary">Match candidates to a job</Button></Link>}>
          When you find good candidates for a job, save them as a list to come back to later or export.
        </Empty>
      )}
      <ul className="tl-stagger grid gap-4 sm:grid-cols-2" data-testid="saved-list">
        {list.data?.map((s) => (
          <li key={s.id}>
            <Link to={`/saved/${s.id}`} className="flex h-full flex-col gap-2 rounded-[12px] border border-line bg-surface p-5 shadow-e1 transition-colors hover:border-ink">
              <span className="flex items-center gap-2 text-[16px] font-semibold">
                <Bookmark className="size-4 text-ink" />
                <span className="truncate">{s.name}</span>
              </span>
              {s.title && s.title !== s.name && <span className="truncate text-[13px] text-muted">For: {s.title}</span>}
              <span className="mt-auto flex items-center gap-3 text-[13px] text-muted">
                <span className="inline-flex items-center gap-1">
                  <Users className="size-3.5" /> {s.count} candidate{s.count === 1 ? '' : 's'}
                </span>
                <span>Saved {timeAgo(s.created_at)}</span>
              </span>
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
  const [renaming, setRenaming] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['shortlist', id], queryFn: () => api.getShortlist(id) })
  const del = useMutation({
    mutationFn: () => api.deleteShortlist(id),
    onSuccess: () => {
      toast('List deleted')
      qc.invalidateQueries({ queryKey: ['shortlists'] })
      navigate('/saved')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const rename = useMutation({
    mutationFn: (name: string) => api.renameShortlist(id, name),
    onSuccess: () => {
      setRenaming(null)
      qc.invalidateQueries({ queryKey: ['shortlist', id] })
      qc.invalidateQueries({ queryKey: ['shortlists'] })
      toast('List renamed')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  if (q.isLoading) return <div className="mx-auto max-w-5xl px-4 py-8 md:px-8"><Skeleton className="h-40" /></div>
  if (q.error || !q.data) return <p className="m-8 text-sm text-danger">{(q.error as Error)?.message ?? 'Not found'}</p>
  const s = q.data
  const highlight = [...s.requirements.must_have_skills, ...s.requirements.nice_to_have_skills]

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8 md:py-8">
      <Link to="/saved" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ArrowLeft className="size-4" /> All saved lists
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight md:text-[28px]" data-testid="saved-title">
            {s.name}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {s.results.length} candidates · saved {timeAgo(s.created_at)}
            {s.requirements.title ? ` · for ${s.requirements.title}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setRenaming(s.name)} data-testid="rename">
            <Pencil className="size-4" /> Rename
          </Button>
          <a href={api.exportUrl(id)} download>
            <Button size="sm" tabIndex={-1}>
              <Download className="size-4" /> Export CSV
            </Button>
          </a>
          <Button size="sm" variant="danger" onClick={() => setConfirm(true)} data-testid="delete">
            <Trash2 className="size-4" /> Delete
          </Button>
        </div>
      </div>

      {s.requirements.must_have_skills.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {s.requirements.must_have_skills.map((k) => (
            <Chip key={k} tone="ink">
              {k}
            </Chip>
          ))}
        </div>
      )}

      <Card className="mt-5 divide-y divide-line">
        {s.results.map((cv) => {
          const name = displayName(cv)
          return (
            <div key={cv.id} className="flex flex-wrap items-center gap-4 p-4">
              <span className="w-6 text-right text-[13px] text-muted tabular-nums">{cv.rank}</span>
              <Avatar name={name} size={38} />
              <div className="min-w-0 flex-1">
                <button type="button" className="text-left font-semibold hover:underline" onClick={() => setOpenId(cv.id)}>
                  {name}
                </button>
                <p className="truncate text-sm text-muted">{[cv.title, years(cv.years_exp), cv.location].filter(Boolean).join(' · ')}</p>
              </div>
              {cv.breakdown && (
                <div className="flex flex-col items-end gap-1">
                  <span className="text-[12px] font-medium text-muted">{matchLabel(cv.score).label}</span>
                  <ScoreBar score={cv.score} breakdown={cv.breakdown} />
                </div>
              )}
            </div>
          )
        })}
      </Card>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Delete this list?"
        description={`“${s.name}” will be removed. The resumes themselves stay in your library.`}
        confirmLabel="Delete list"
        danger
        busy={del.isPending}
        onConfirm={() => del.mutate()}
      />
      <Modal
        open={renaming !== null}
        onOpenChange={(o) => !o && setRenaming(null)}
        title="Rename list"
        footer={
          <>
            <Button onClick={() => setRenaming(null)}>Cancel</Button>
            <Button variant="primary" disabled={!renaming?.trim()} busy={rename.isPending} onClick={() => rename.mutate(renaming!.trim())} data-testid="rename-confirm">
              Save name
            </Button>
          </>
        }
      >
        <Label htmlFor="rename">Name</Label>
        <Input id="rename" autoFocus value={renaming ?? ''} onChange={(e) => setRenaming(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && renaming?.trim() && rename.mutate(renaming.trim())} />
      </Modal>
      <CandidateProfile cvId={openId} onClose={() => setOpenId(null)} highlight={highlight} />
    </div>
  )
}
