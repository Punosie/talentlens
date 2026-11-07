import { useQuery } from '@tanstack/react-query'
import { FileArchive, FileStack, FolderOpen, FolderUp, ShieldCheck, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Button, Card, ConfirmDialog, PageHeader, useToast } from '../components/ui'
import { api } from '../lib/api'
import { cn } from '../lib/utils'
import { RESUME_EXT, isAccepted, useUploads } from '../upload/UploadContext'

const CONFIRM_ABOVE = 25

export default function AddPage() {
  const { add } = useUploads()
  const toast = useToast()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const filesRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const zipRef = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [pending, setPending] = useState<{ files: File[]; source: string } | null>(null)

  const start = (files: File[]) => {
    const { accepted, ignored } = add(files)
    if (!accepted) toast('No resume files found. Use PDF, Word (DOCX/DOC) or a ZIP.', 'error')
    else if (ignored) toast(`${ignored} other file${ignored === 1 ? ' was' : 's were'} skipped (not a resume).`)
  }

  const offer = (list: FileList | File[] | null, source: string) => {
    if (!list) return
    const files = Array.from(list).filter((f) => isAccepted(f.name) && !f.name.startsWith('~$') && !f.name.startsWith('.'))
    const ignored = Array.from(list).length - files.length
    if (!files.length) {
      toast('No resume files found there. TalentLens imports PDF, Word (DOCX/DOC) and ZIP files.', 'error')
      return
    }
    if (files.length > CONFIRM_ABOVE) setPending({ files, source })
    else start(files)
    if (ignored && files.length <= CONFIRM_ABOVE) toast(`${ignored} other file${ignored === 1 ? ' was' : 's were'} skipped (not a resume).`)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    offer(e.dataTransfer.files, 'the files you dropped')
  }

  const options = [
    {
      icon: FileStack,
      title: 'Choose files',
      text: 'Pick one or many resumes (PDF, DOCX, DOC).',
      onClick: () => filesRef.current?.click(),
      testid: 'add-files',
    },
    {
      icon: FolderUp,
      title: 'Choose a folder',
      text: 'Import every resume in a folder, including subfolders.',
      onClick: () => folderRef.current?.click(),
      testid: 'add-folder',
    },
    {
      icon: FileArchive,
      title: 'Upload a ZIP',
      text: 'A .zip of resumes (up to 300 MB, 2,000 files).',
      onClick: () => zipRef.current?.click(),
      testid: 'add-zip',
    },
  ]

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <PageHeader
        title="Add resumes"
        description="Bring in one resume or thousands. They're copied into your resume folder and become searchable automatically."
      />

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={cn(
          'flex flex-col items-center justify-center gap-3 rounded-[14px] border-2 border-dashed px-6 py-12 text-center transition-colors',
          drag ? 'border-ink bg-ink-soft' : 'border-line-strong bg-surface',
        )}
      >
        <span className="flex size-14 items-center justify-center rounded-full bg-ink-soft text-ink">
          <Upload className="size-6" />
        </span>
        <p className="text-[17px] font-semibold">Drag and drop resumes here</p>
        <p className="text-sm text-muted">PDF, Word (DOCX or DOC), or a ZIP · up to 20 MB per resume</p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        {options.map(({ icon: Icon, title, text, onClick, testid }) => (
          <button
            key={title}
            type="button"
            onClick={onClick}
            data-testid={testid}
            className="flex flex-col items-start gap-2 rounded-[12px] border border-line bg-surface p-5 text-left shadow-e1 transition-colors hover:border-ink focus-visible:border-ink"
          >
            <Icon className="size-6 text-ink" />
            <span className="text-[15px] font-semibold">{title}</span>
            <span className="text-[13px] text-muted">{text}</span>
          </button>
        ))}
      </div>

      <input ref={filesRef} type="file" hidden multiple accept={RESUME_EXT.join(',')} data-testid="file-input" onChange={(e) => {
          offer(e.target.files, 'the selected files')
          e.target.value = ''
        }} />
      <input
        ref={folderRef}
        type="file"
        hidden
        multiple
        data-testid="folder-input"
        {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
        onChange={(e) => {
          const files = e.target.files
          const top = files?.[0]?.webkitRelativePath.split('/')[0]
          offer(files, top ? `“${top}”` : 'that folder')
          e.target.value = ''
        }}
      />
      <input ref={zipRef} type="file" hidden accept=".zip" data-testid="zip-input" onChange={(e) => {
          offer(e.target.files, 'the ZIP')
          e.target.value = ''
        }} />

      <Card className="mt-8 flex gap-4 p-5">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-ok" />
        <div className="text-[13.5px] leading-relaxed">
          <p className="font-semibold">Safe by design</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
            <li>New files are added next to your existing resumes. Nothing already there is changed, renamed or deleted.</li>
            <li>A resume that's already in your library is recognised and skipped, even if its name is different.</li>
            <li>Everything stays on this computer.</li>
          </ul>
          {settings.data?.cv_dir && (
            <p className="mt-3 flex flex-wrap items-center gap-2 text-muted">
              <FolderOpen className="size-4" /> Saving into <code className="text-[12.5px] text-text">{settings.data.cv_dir}</code>
              <Button size="sm" variant="ghost" onClick={() => api.revealFolder().catch(() => undefined)}>
                Show folder
              </Button>
            </p>
          )}
        </div>
      </Card>

      <ConfirmDialog
        open={!!pending}
        onOpenChange={(o) => !o && setPending(null)}
        title={`Import ${pending?.files.length ?? 0} resumes?`}
        description={`From ${pending?.source}. They'll be uploaded in small batches. You can keep working while they import, and progress shows at the bottom right.`}
        confirmLabel="Import"
        onConfirm={() => {
          if (pending) start(pending.files)
          setPending(null)
        }}
      />
    </div>
  )
}
