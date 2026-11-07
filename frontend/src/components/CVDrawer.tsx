import * as Dialog from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { Briefcase, Download, ExternalLink, Mail, MapPin, Phone, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import { displayName, years } from '../lib/utils'
import { Button, Chip, Spinner } from './ui'

export function CVDrawer({
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
  const [showText, setShowText] = useState(false)
  const hl = new Set(highlight.map((s) => s.toLowerCase()))
  const cv = q.data

  return (
    <Dialog.Root open={cvId !== null} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25 dark:bg-black/50" />
        <Dialog.Content
          className="fixed top-0 right-0 z-50 flex h-full w-full max-w-[640px] flex-col border-l border-line-strong bg-surface shadow-2xl outline-none"
          data-testid="cv-drawer"
          aria-describedby={undefined}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-xl font-bold tracking-tight">
                {cv ? displayName(cv) : 'Loading…'}
              </Dialog.Title>
              {cv?.title && <p className="mt-0.5 text-sm text-muted">{cv.title}</p>}
            </div>
            <Dialog.Close
              className="flex size-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-text"
              aria-label="Close"
            >
              <X className="size-5" />
            </Dialog.Close>
          </div>

          {q.isLoading && (
            <div className="p-6">
              <Spinner />
            </div>
          )}
          {q.error && <p className="p-6 text-sm text-danger">{(q.error as Error).message}</p>}

          {cv && (
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="primary" onClick={() => window.open(api.fileUrl(cv.id), '_blank')}>
                  <ExternalLink className="size-4" /> Open original
                </Button>
                <a href={api.fileUrl(cv.id, true)} download>
                  <Button size="sm" tabIndex={-1}>
                    <Download className="size-4" /> Download
                  </Button>
                </a>
              </div>

              <dl className="mt-5 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
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
                  <p className="text-sm leading-relaxed">{cv.summary}</p>
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
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {cv.education.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </Section>
              )}

              <Section title="Source">
                <p className="text-[13px] break-all text-muted">
                  {cv.filename} · {cv.ext.toUpperCase()}
                  {cv.pages ? ` · ${cv.pages} page${cv.pages > 1 ? 's' : ''}` : ''}
                  {cv.ocr_used ? ' · read with OCR' : ''} ·{' '}
                  {cv.extractor === 'llm' ? 'fields by local AI' : 'fields by rules (AI pending)'}
                </p>
                {Object.keys(cv.provenance).length > 0 && (
                  <dl className="mt-2 space-y-1 text-[13px]">
                    {Object.entries(cv.provenance).map(([k, v]) => (
                      <div key={k} className="flex gap-2">
                        <dt className="w-32 shrink-0 text-muted">{k.replace(/_/g, ' ')}</dt>
                        <dd className="min-w-0 break-words">{v}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </Section>

              <Section title="Resume text">
                <button
                  type="button"
                  className="text-sm font-medium text-ink underline underline-offset-2"
                  onClick={() => setShowText((s) => !s)}
                >
                  {showText ? 'Hide text' : 'Show extracted text'}
                </button>
                {showText && (
                  <pre className="mt-3 max-h-[480px] overflow-auto rounded-md bg-sunken p-4 font-sans text-[13px] leading-relaxed whitespace-pre-wrap">
                    {cv.text}
                  </pre>
                )}
              </Section>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 text-muted">{icon}</span>
      <div className="min-w-0">
        <dt className="text-[12px] text-muted">{label}</dt>
        <dd className="break-words">{children}</dd>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-6 border-t border-line pt-4">
      <h3 className="mb-2 text-[13px] font-semibold">{title}</h3>
      {children}
    </section>
  )
}
