import type { Breakdown } from '../lib/api'

export const SEGMENTS: { key: keyof Breakdown; label: string; color: string }[] = [
  { key: 'semantic', label: 'Overall fit', color: 'var(--seg-semantic)' },
  { key: 'must', label: 'Must-have skills', color: 'var(--seg-must)' },
  { key: 'nice', label: 'Nice-to-have', color: 'var(--seg-nice)' },
  { key: 'experience', label: 'Experience', color: 'var(--seg-experience)' },
  { key: 'domain', label: 'Industry', color: 'var(--seg-domain)' },
  { key: 'location', label: 'Location', color: 'var(--seg-location)' },
]

/** One bar, 0-100, split into the six weighted parts that make up the score. */
export function ScoreBar({ score, breakdown, weights }: { score: number; breakdown: Breakdown; weights?: Breakdown }) {
  const tip = SEGMENTS.map(
    (s) => `${s.label}: ${breakdown[s.key].toFixed(1)}${weights ? ` / ${weights[s.key]}` : ''}`,
  ).join('\n')
  return (
    <div className="flex items-center gap-3" title={tip}>
      <span className="w-10 text-right text-lg font-bold tabular-nums" data-testid="score">
        {Math.round(score)}
      </span>
      <div
        className="flex h-2.5 w-36 overflow-hidden rounded-sm bg-sunken"
        role="img"
        aria-label={`Score ${Math.round(score)} of 100. ${tip.replace(/\n/g, '; ')}`}
      >
        {SEGMENTS.map((s) => (
          <span key={s.key} style={{ width: `${breakdown[s.key]}%`, background: s.color }} />
        ))}
      </div>
    </div>
  )
}

export function ScoreLegend({ weights }: { weights?: Breakdown }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
      {SEGMENTS.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} />
          {s.label}
          {weights ? ` ${weights[s.key]}` : ''}
        </li>
      ))}
    </ul>
  )
}
