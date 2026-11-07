import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp, ListChecks, Lock, Search, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { api, type IndexStatus } from '../lib/api'
import { FolderPicker } from './FolderPicker'
import { Button, Modal, Progress } from './ui'

/** First-run guide: choose folder → reading → ready. Re-openable from Help. */
export function Onboarding({
  open,
  onClose,
  status,
  firstRun,
}: {
  open: boolean
  onClose: () => void
  status: IndexStatus | null
  firstRun: boolean
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [step, setStep] = useState<0 | 1 | 2>(0)
  const s = settings.data

  const finish = async (to?: string) => {
    await api.updateSettings({ onboarded: true }).catch(() => undefined)
    qc.invalidateQueries({ queryKey: ['settings'] })
    setStep(0)
    onClose()
    if (to) navigate(to)
  }

  const indexing = status && (status.state === 'running' || status.state === 'queued')
  const resumes = status?.counts?.indexed ?? 0

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && !firstRun && onClose()}
      dismissable={!firstRun || step === 2}
      wide
      title={step === 0 ? 'Welcome to TalentLens' : step === 1 ? 'Reading your resumes' : "You're all set"}
      description={
        step === 0
          ? 'Your private resume library. Search resumes and match people to jobs, all on this computer.'
          : step === 1
            ? 'TalentLens is reading each resume so you can search it. You can keep using the app meanwhile.'
            : `${resumes} resume${resumes === 1 ? ' is' : 's are'} ready. What would you like to do first?`
      }
    >
      <ol className="mb-6 flex gap-2" aria-label="Setup steps">
        {['Choose folder', 'Read resumes', 'Start'].map((label, i) => (
          <li key={label} className="flex flex-1 flex-col gap-1.5">
            <span className={`h-1 rounded-full ${i <= step ? 'bg-ink' : 'bg-line'}`} />
            <span className={`text-[12px] ${i === step ? 'font-semibold text-text' : 'text-muted'}`}>
              {i + 1}. {label}
            </span>
          </li>
        ))}
      </ol>

      {step === 0 && s && (
        <div className="space-y-5">
          <div>
            <h3 className="text-[15px] font-semibold">Where are your resumes?</h3>
            <p className="mt-1 text-[13px] text-muted">
              Choose the folder that holds your resume files (PDF or Word). TalentLens only <b>reads</b> them. Your files
              are never changed, moved or uploaded anywhere. New resumes you add later are saved into this folder.
            </p>
          </div>
          {s.cv_dir_locked ? (
            <p className="text-sm">
              Your folder is set by the configuration file: <code className="text-[13px]">{s.cv_dir}</code>
            </p>
          ) : (
            <FolderPicker
              initial={s.cv_dir}
              platform={s.platform}
              submitLabel="Use this folder and continue"
              onChosen={() => {
                qc.invalidateQueries()
                setStep(1)
              }}
            />
          )}
          {s.cv_dir_locked && <Button variant="primary" onClick={() => setStep(1)}>Continue</Button>}
          <p className="flex items-center gap-2 border-t border-line pt-4 text-[12px] text-muted">
            <Lock className="size-3.5" /> Everything stays on this computer, including the AI.
          </p>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-4" aria-live="polite">
          <Progress value={indexing && status?.total ? status.done / status.total : indexing ? 0.05 : 1} label="Reading resumes" />
          <p className="text-sm">
            {indexing
              ? status?.total
                ? `Read ${status.done} of ${status.total} resumes…`
                : 'Looking for resumes in your folder…'
              : `Done: ${resumes} resume${resumes === 1 ? '' : 's'} ready to search.`}
          </p>
          <p className="flex items-start gap-2 rounded-md bg-sunken p-3 text-[13px] text-muted">
            <Sparkles className="mt-0.5 size-4 shrink-0" />
            After this, <b>smart reading</b> quietly improves names, job titles and experience in the
            background. You'll see its progress at the top of the screen.
          </p>
          <div className="flex justify-end">
            <Button variant="primary" onClick={() => setStep(2)} data-testid="onboarding-next">
              {indexing ? 'Continue while it reads' : 'Continue'}
            </Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { to: '/match', icon: ListChecks, title: 'Match to a job', text: 'Paste a job description, get ranked candidates.' },
            { to: '/search', icon: Search, title: 'Search resumes', text: 'Find people by skill, experience or place.' },
            { to: '/add', icon: FileUp, title: 'Add resumes', text: 'Import files, a whole folder or a ZIP.' },
          ].map(({ to, icon: Icon, title, text }) => (
            <button
              key={to}
              type="button"
              onClick={() => finish(to)}
              className="flex flex-col items-start gap-2 rounded-[10px] border border-line p-4 text-left transition-colors hover:border-ink hover:bg-sunken"
            >
              <Icon className="size-5 text-ink" />
              <span className="font-semibold">{title}</span>
              <span className="text-[13px] text-muted">{text}</span>
            </button>
          ))}
          <div className="sm:col-span-3 flex justify-end">
            <Button variant="ghost" onClick={() => finish()} data-testid="onboarding-done">
              Go to home
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
