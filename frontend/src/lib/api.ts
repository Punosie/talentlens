// Typed client for the TalentLens local API.

export type CVSummary = {
  id: number
  filename: string
  ext: string
  status: 'indexed' | 'unreadable' | 'error' | 'pending'
  error: string | null
  name: string | null
  title: string | null
  email: string | null
  phone: string | null
  location: string | null
  city?: string | null
  country?: string | null
  years_exp: number | null
  skills: string[]
  domains: string[]
  summary: string | null
  ocr_used: boolean
  pages: number | null
  extractor: string | null
  added_at: string
  indexed_at: string | null
  score?: number
  snippet?: string | null
  matched_skills?: string[]
}

export type CVDetail = CVSummary & {
  size: number
  sha256: string
  text: string
  education: string[]
  parser: string | null
  provenance: Record<string, string>
}

export type Facet = { value: string; count: number }
export type Facets = {
  skills: Facet[]
  domains: Facet[]
  countries: Facet[]
  cities: (Facet & { country: string | null })[]
  years: { min: number | null; max: number | null; known: number; total: number; buckets: Record<string, number> }
}

export type IndexStatus = {
  state: 'idle' | 'queued' | 'running' | 'enhancing'
  kind: string | null
  reason: string | null
  total: number
  done: number
  current: string
  started_at: string | null
  finished_at: string | null
  last_report: Record<string, unknown> | null
  version: number
  errors: { file: string; error: string }[]
  ai_pending: number
  ai_paused: boolean
  counts: Record<string, number>
  last_index_at: string | null
}

export type Health = {
  status: string
  version: string
  cv_dir: string
  cv_dir_exists: boolean
  llm: { mode: string; model?: string; available: boolean; error: string | null }
  embed_model: string
}

export type SearchParams = {
  q?: string
  skills?: string[]
  skills_mode?: 'all' | 'any'
  years_min?: number | null
  years_max?: number | null
  location?: string[]
  domain?: string[]
  sort?: 'relevance' | 'recent' | 'experience' | 'name'
  limit?: number
  offset?: number
}

export type Requirements = {
  title: string | null
  must_have_skills: string[]
  nice_to_have_skills: string[]
  min_years: number | null
  max_years: number | null
  locations: string[]
  domains: string[]
  summary: string | null
  source: string
}

export type Breakdown = Record<'semantic' | 'must' | 'nice' | 'experience' | 'domain' | 'location', number>

export type RankedCV = CVSummary & {
  rank: number
  score: number
  breakdown: Breakdown
  matched_must: string[]
  missing_must: string[]
  matched_nice: string[]
  other_files?: { id: number; filename: string }[]
}

export type ShortlistResult = {
  total: number
  items: RankedCV[]
  weights: Breakdown
  timings: Record<string, number>
}

export type UploadResult = {
  added: number
  results: { filename: string; status: 'added' | 'duplicate' | 'rejected'; message: string; saved_as?: string }[]
}

export type SavedShortlist = { id: number; name: string; created_at: string; count: number; title: string | null }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

function qs(params: Record<string, unknown>): string {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)))
    else u.append(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/api/health'),
  status: () => request<IndexStatus>('/api/index/status'),
  refresh: (full = false) => request<IndexStatus>(`/api/index/refresh${qs({ full })}`, { method: 'POST' }),
  setAiPaused: (paused: boolean) => request<IndexStatus>(`/api/index/ai${qs({ paused })}`, { method: 'POST' }),
  search: (p: SearchParams) => request<{ total: number; items: CVSummary[] }>(`/api/search${qs(p)}`),
  facets: () => request<Facets>('/api/facets'),
  cv: (id: number) => request<CVDetail>(`/api/cvs/${id}`),
  fileUrl: (id: number, download = false) => `/api/cvs/${id}/file${download ? '?download=true' : ''}`,
  upload: (files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f, f.name))
    return request<UploadResult>('/api/cvs', { method: 'POST', body: fd })
  },
  parseJd: (input: { text?: string; file?: File; mode: 'rules' | 'ai' }) => {
    const fd = new FormData()
    if (input.text) fd.append('text', input.text)
    if (input.file) fd.append('file', input.file, input.file.name)
    fd.append('mode', input.mode)
    return request<{ jd_text: string; requirements: Requirements; warning: string | null }>('/api/jd/parse', {
      method: 'POST',
      body: fd,
    })
  },
  shortlist: (requirements: Requirements, jd_text: string, limit = 50) =>
    request<ShortlistResult>('/api/shortlist', json({ requirements, jd_text, limit })),
  explain: (cv_id: number, requirements: Requirements) =>
    request<{ reason: string; strengths: string[]; gaps: string[] }>('/api/shortlist/explain', json({ cv_id, requirements })),
  saveShortlist: (body: { name: string; jd_text: string; requirements: Requirements; results: RankedCV[] }) =>
    request<{ id: number; name: string }>('/api/shortlists', json(body)),
  shortlists: () => request<SavedShortlist[]>('/api/shortlists'),
  getShortlist: (id: number) =>
    request<{ id: number; name: string; created_at: string; jd_text: string; requirements: Requirements; results: RankedCV[] }>(
      `/api/shortlists/${id}`,
    ),
  deleteShortlist: (id: number) => request<void>(`/api/shortlists/${id}`, { method: 'DELETE' }),
  exportUrl: (id: number) => `/api/shortlists/${id}/export.csv`,
  exportUnsaved: async (body: { name: string; jd_text: string; requirements: Requirements; results: RankedCV[] }) => {
    const res = await fetch('/api/shortlist/export', json(body))
    if (!res.ok) throw new ApiError(res.status, 'Export failed')
    return res.blob()
  },
}
