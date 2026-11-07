import clsx, { type ClassValue } from 'clsx'

export const cn = (...v: ClassValue[]) => clsx(v)

export function years(y: number | null | undefined): string {
  if (y === null || y === undefined) return 'Years not found'
  const r = Math.round(y * 10) / 10
  return `${r % 1 === 0 ? r.toFixed(0) : r} yr${r === 1 ? '' : 's'}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const t = new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export function displayName(cv: { name: string | null; filename: string }): string {
  return cv.name || cv.filename.replace(/\.(pdf|docx?|txt)$/i, '')
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Split a snippet that marks hits as [[term]] into parts for safe rendering. */
export function snippetParts(s: string): { text: string; hit: boolean }[] {
  const out: { text: string; hit: boolean }[] = []
  const re = /\[\[(.+?)\]\]/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({ text: s.slice(last, m.index), hit: false })
    out.push({ text: m[1], hit: true })
    last = m.index + m[0].length
  }
  if (last < s.length) out.push({ text: s.slice(last), hit: false })
  return out
}
