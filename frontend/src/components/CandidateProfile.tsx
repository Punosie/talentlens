import * as Dialog from '@radix-ui/react-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { useQuery } from '@tanstack/react-query'
import { Briefcase, Download, ExternalLink, GraduationCap, Mail, MapPin, Phone, Sparkles, X } from 'lucide-react'
import { type ReactNode } from 'react'
import { api } from '../lib/api'
import { cn, displayName, years } from '../lib/utils'
import { Avatar, Button, Chip, Skeleton } from './ui'

/** Candidate profile side panel with Overview / Resume / Source tabs. */
export function CandidateProfile({
  cvId,
  onClose,
  highlight = [],
  extra,
}: {
  cvId: number | null
  onClose: () => void
  highlight?: string[]
  extra?: ReactNode
}) {
  const q = useQuery({ queryKey: ['cv', cvId], queryFn: () => api.cv(cvId!), enabled: cvId !== null })
  const hl = new Set(highlight.map((s) => s.toLowerCase()))
  const cv = q.data
  const name = cv ? displayName(cv) : ''
  const isLinkedIn = cv?.source === 'linkedin'

  return (
    <Dialog.Root open={cvId !== null} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="tl-overlay fixed inset-0 z-40 bg-black/25 dark:bg-black/50" />
        <Dialog.Content
          className="tl-drawer fixed top-0 right-0 z-50 flex h-full w-full max-w-[760px] flex-col border-l border-line bg-surface shadow-e2 outline-none"
          data-testid="cv-drawer"
          aria-describedby={undefined}
        >
          <div className="flex items-start gap-4 border-b border-line px-6 py-5">
            {cv ? <Avatar name={name} size={52} /> : <Skeleton className="size-[52px] rounded-full" />}
            <div className="min-w-0 flex-1">
              <Dialog.Title className="truncate text-xl font-bold tracking-tight">{cv ? name : 'Loading…'}</Dialog.Title>
              <p className="mt-0.5 truncate text-sm text-muted">{cv?.title || (cv ? 'Job title not found' : '')}</p>
              {cv && isLinkedIn && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {cv.profile_url && (
                    <Button size="sm" variant="primary" onClick={() => window.open(cv.profile_url!, '_blank', 'noopener')}>
                      <ExternalLink className="size-4" /> Open on LinkedIn
                    </Button>
                  )}
                  <SourceBadges cv={cv} />
                </div>
              )}
              {cv && !isLinkedIn && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="primary" onClick={() => window.open(api.fileUrl(cv.id), '_blank')}>
                    <ExternalLink className="size-4" /> Open original
                  </Button>
                  <a href={api.fileUrl(cv.id, true)} download>
                    <Button size="sm" tabIndex={-1}>
                      <Download className="size-4" /> Download
                    </Button>
                  </a>
                  {cv.person_id && !cv.person_id.startsWith('cv:') && <Chip tone="ink">Linked to a LinkedIn connection</Chip>}
                </div>
              )}
            </div>
            <Dialog.Close
              className="flex size-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-text"
              aria-label="Close"
            >
              <X className="size-5" />
            </Dialog.Close>
          </div>

          {q.isLoading && (
            <div className="space-y-3 p-6">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}
          {q.error && <p className="p-6 text-sm text-danger">{(q.error as Error).message}</p>}

          {cv && (
            <Tabs.Root defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
              <Tabs.List className="flex gap-1 border-b border-line px-6" aria-label="Candidate details">
                {[
                  ['overview', 'Overview'],
                  ['resume', isLinkedIn ? 'Profile' : 'Resume'],
                  ['source', isLinkedIn ? 'Source' : 'File & source'],
                ].map(([v, l]) => (
                  <Tabs.Trigger
                    key={v}
                    value={v}
                    className={cn(
                      '-mb-px border-b-2 border-transparent px-3 py-2.5 text-[14px] font-medium text-muted',
                      'hover:text-text data-[state=active]:border-ink data-[state=active]:text-text',
                    )}
                  >
                    {l}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>

              <Tabs.Content value="overview" className="tl-stagger min-h-0 flex-1 overflow-y-auto px-6 py-5 outline-none">
                <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  <Fact icon={<Briefcase className="size-4" />} label="Experience">
                    {years(cv.years_exp)}
                  </Fact>
                  <Fact icon={<MapPin className="size-4" />} label="Location">
                    {cv.location || 'Not found'}
                  </Fact>
                  {cv.email && (
                    <Fact icon={<Mail className="size-4" />} label="Email">
                      <a className="underline decoration-line-strong underline-offset-2" href={`mailto:${cv.email}`}>
                        {cv.email}
                      </a>
                    </Fact>
                  )}
                  {cv.phone && (
                    <Fact icon={<Phone className="size-4" />} label="Phone">
                      {cv.phone}
                    </Fact>
                  )}
                </dl>
                {extra}
                {cv.summary && (
                  <Section title="Summary">
                    <p className="text-[14px] leading-relaxed">{cv.summary}</p>
                  </Section>
                )}
                <Section title={`Skills (${cv.skills.length})`}>
                  <div className="flex flex-wrap gap-1.5">
                    {cv.skills.map((s) => (
                      <Chip key={s} tone={hl.has(s.toLowerCase()) ? 'mark' : 'plain'}>
                        {s}
                      </Chip>
                    ))}
                    {!cv.skills.length && <span className="text-sm text-muted">No skills recognised</span>}
                  </div>
                </Section>
                {cv.domains.length > 0 && (
                  <Section title="Industries">
                    <div className="flex flex-wrap gap-1.5">
                      {cv.domains.map((d) => (
                        <Chip key={d} tone="ink">
                          {d}
                        </Chip>
                      ))}
                    </div>
                  </Section>
                )}
                {cv.education.length > 0 && (
                  <Section title="Education">
                    <ul className="space-y-1.5 text-sm">
                      {cv.education.map((e) => (
                        <li key={e} className="flex gap-2">
                          <GraduationCap className="mt-0.5 size-4 shrink-0 text-muted" />
                          {e}
                        </li>
                      ))}
                    </ul>
                  </Section>
                )}
                <p className="mt-6 flex items-center gap-1.5 text-[12px] text-muted">
                  <Sparkles className="size-3.5" />
                  {cv.extractor === 'llm' ? 'Details checked by smart reading' : 'Details read automatically'}
                </p>
              </Tabs.Content>

              <Tabs.Content value="resume" className="min-h-0 flex-1 outline-none">
                {isLinkedIn ? (
                  <div className="h-full overflow-y-auto px-6 py-5">
                    <p className="mb-3 text-[12px] text-muted">LinkedIn profile from your connections database.</p>
                    <pre className="font-sans text-[13.5px] leading-relaxed whitespace-pre-wrap">{cv.text}</pre>
                  </div>
                ) : cv.ext === 'pdf' ? (
                  <iframe
                    title={`Resume of ${name}`}
                    src={`${api.fileUrl(cv.id)}#view=FitH`}
                    className="h-full w-full border-0 bg-sunken"
                  />
                ) : (
                  <div className="h-full overflow-y-auto px-6 py-5">
                    <p className="mb-3 text-[12px] text-muted">
                      Word documents are shown as text. Use “Open original” to see the formatted file.
                    </p>
                    <pre className="font-sans text-[13.5px] leading-relaxed whitespace-pre-wrap">{cv.text}</pre>
                  </div>
                )}
              </Tabs.Content>

              <Tabs.Content value="source" className="min-h-0 flex-1 overflow-y-auto px-6 py-5 outline-none">
                {isLinkedIn ? (
                  <dl className="space-y-3 text-sm">
                    <Row label="Source">LinkedIn (connections database)</Row>
                    <Row label="Connected via">
                      {cv.owners?.length ? cv.owners.map((o) => `@${o}`).join(', ') : 'Unknown'}
                    </Row>
                    {cv.profile_url && (
                      <Row label="Profile">
                        <a className="underline underline-offset-2" href={cv.profile_url} target="_blank" rel="noopener noreferrer">
                          {cv.profile_url.replace(/^https?:\/\/(www\.)?/, '')}
                        </a>
                      </Row>
                    )}
                  </dl>
                ) : (
                <dl className="space-y-3 text-sm">
                  <Row label="File">{cv.filename}</Row>
                  <Row label="Type">
                    {cv.ext.toUpperCase()}
                    {cv.pages ? ` · ${cv.pages} page${cv.pages > 1 ? 's' : ''}` : ''}
                    {cv.ocr_used ? ' · scanned (read with OCR)' : ''}
                  </Row>
                  <Row label="Size">{(cv.size / 1024).toFixed(0)} KB</Row>
                  {Object.entries(cv.provenance).map(([k, v]) => (
                    <Row key={k} label={k.replace(/_/g, ' ')}>
                      {v}
                    </Row>
                  ))}
                </dl>
                )}
                <details className="mt-6 text-sm">
                  <summary className="cursor-pointer font-medium text-ink">Show the text TalentLens read</summary>
                  <pre className="mt-3 max-h-[420px] overflow-auto rounded-md bg-sunken p-4 font-sans text-[13px] leading-relaxed whitespace-pre-wrap">
                    {cv.text}
                  </pre>
                </details>
              </Tabs.Content>
            </Tabs.Root>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 text-muted">{icon}</span>
      <div className="min-w-0">
        <dt className="text-[12px] text-muted">{label}</dt>
        <dd className="font-medium break-words">{children}</dd>
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
      <dt className="text-muted capitalize">{label}</dt>
      <dd className="break-words">{children}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-6 border-t border-line pt-4">
      <h3 className="mb-2.5 text-[13px] font-semibold">{title}</h3>
      {children}
    </section>
  )
}

/** "LinkedIn · via @handle" badges for a synced connection. */
export function SourceBadges({ cv }: { cv: { source?: string; owners?: string[] } }) {
  if (cv.source !== 'linkedin') return null
  const owners = cv.owners ?? []
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Chip tone="ink">LinkedIn</Chip>
      {owners.length > 0 && (
        <span className="text-[12px] text-muted" title={owners.map((o) => `@${o}`).join(', ')}>
          via {owners.length === 1 ? `@${owners[0]}` : `${owners.length} accounts`}
        </span>
      )}
    </span>
  )
}
