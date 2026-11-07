import { BookOpen, ChevronDown } from 'lucide-react'
import { type ReactNode } from 'react'
import { Link } from 'react-router'
import { SEGMENTS } from '../components/ScoreBar'
import { Button, Card, PageHeader } from '../components/ui'

const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: 'Is my data uploaded anywhere?',
    a: 'No. TalentLens runs entirely on this computer, including the AI. Your resumes and searches never leave it, and it even works without internet once installed.',
  },
  {
    q: 'Will TalentLens change or delete my resume files?',
    a: 'Never. It only reads them. When you add new resumes, they are saved as new files next to the existing ones; a resume that is already there is recognised and skipped.',
  },
  {
    q: 'How do I add many resumes at once?',
    a: (
      <>
        Go to <Link to="/add" className="font-medium text-ink underline">Add resumes</Link> and choose a whole folder or a
        ZIP file. You can keep working while they import; progress shows at the bottom right.
      </>
    ),
  },
  {
    q: 'How is the match score calculated?',
    a: (
      <>
        Each candidate gets up to 100 points, split into six parts:
        <ul className="mt-2 space-y-1">
          {SEGMENTS.map((s) => (
            <li key={s.key} className="flex items-center gap-2">
              <span className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
        <p className="mt-2">
          “Excellent” is 75 or more, “Strong” 60 or more, “Fair” 45 or more. Click “Why this score?” on any candidate for a
          short explanation in plain words.
        </p>
      </>
    ),
  },
  {
    q: 'What is “smart reading”?',
    a: 'A small AI model on this computer that double-checks each resume, such as the person’s name, current job title and years of experience. It runs quietly in the background. You can pause it from the status button at the top, or turn it off in Settings; everything still works without it.',
  },
  {
    q: 'Why is a resume marked “couldn’t read”?',
    a: 'The file is empty, damaged or password-protected, or it is an old Word (.doc) file and neither Microsoft Word nor LibreOffice is installed. Open it yourself to check, then save it again as PDF or DOCX.',
  },
  {
    q: 'My resumes moved to another folder. What do I do?',
    a: (
      <>
        Open <Link to="/settings" className="font-medium text-ink underline">Settings</Link> → Resume folder → Change folder.
        Each folder keeps its own library, so switching back later is instant.
      </>
    ),
  },
  {
    q: 'I added files directly to the folder. Why don’t they show up?',
    a: 'TalentLens notices new files automatically within a few seconds. If you don’t see them, click the status button at the top and choose “Check folder for new resumes”.',
  },
]

export default function HelpPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-8 md:px-8">
      <PageHeader
        title="Help"
        description="Quick answers about using TalentLens."
        actions={
          <Button onClick={() => window.dispatchEvent(new Event('tl:open-guide'))}>
            <BookOpen className="size-4" /> Show the welcome guide
          </Button>
        }
      />
      <Card className="divide-y divide-line">
        {FAQ.map(({ q, a }) => (
          <details key={q} className="group px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-[15px] font-medium">
              {q}
              <ChevronDown className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" />
            </summary>
            <div className="mt-2 text-[14px] leading-relaxed text-muted">{a}</div>
          </details>
        ))}
      </Card>
    </div>
  )
}
