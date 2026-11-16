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
  /** file = resume on disk, linkedin = profile synced from the connections database */
  source?: 'file' | 'linkedin'
  owners?: string[]
  profile_url?: string | null
  person_id?: string | null
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
  sources?: Facet[]
  owners?: Facet[]
  skills: Facet[]
  domains: Facet[]
  countries: Facet[]
  /** US states (from the full written location) */
  regions?: (Facet & { country: string | null })[]
  cities: (Facet & { country: string | null })[]
  years: { min: number | null; max: number | null; known: number; total: number; buckets: Record<string, number> }
}

export type IndexStatus = {
  state: 'idle' | 'queued' | 'running' | 'enhancing' | 'no_folder'
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
  ai_done: number
  ai_total: number
  counts: Record<string, number>
  last_index_at: string | null
}

export type Health = {
  status: string
  version: string
  cv_dir: string | null
  cv_dir_exists: boolean
  needs_setup: boolean
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
  source?: ('file' | 'linkedin')[]
  owner?: string[]
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
  other_files?: { id: number; filename: string; source?: string }[]
}

export type ShortlistResult = {
  total: number
  items: RankedCV[]
  weights: Breakdown
  timings: Record<string, number>
  refined: boolean
}

export type UploadResult = {
  added: number
  results: { filename: string; status: 'added' | 'duplicate' | 'rejected'; message: string; saved_as?: string }[]
}

export type SavedShortlist = { id: number; name: string; created_at: string; count: number; title: string | null }

export type AppSettings = {
  version: string
  platform: 'windows' | 'mac' | 'linux'
  cv_dir: string | null
  cv_dir_source: 'config' | 'app' | 'auto' | 'none'
  cv_dir_locked: boolean
  cv_dir_exists: boolean
  provenance_csv: string | null
  data_dir: string
  onboarded: boolean
  ai: {
    enabled: boolean
    locked: boolean
    paused: boolean
    model: string | null
    models: { id: string; label: string; hint: string; size_gb?: number; think?: boolean | null; recommended?: boolean }[]
    /** Tags already pulled into Ollama; null when Ollama isn't reachable */
    installed?: string[] | null
    mode: string
    available: boolean
    error: string | null
  }
  connections: ConnectionsStatus & {
    locked: boolean
    host: string | null
    mode: 'team' | 'mongo' | 'off'
    team: { server: string; name: string } | null
  }
  device?: {
    active: 'cpu' | 'cuda'
    model: string | null
    benchmark: { cpu_per_s?: number | null; cuda_per_s?: number | null; gpu_name?: string | null; choice?: string } | null
  }
}

export type ConnectionsStatus = {
  configured: boolean
  state: 'idle' | 'pulling' | 'pushing' | 'error' | 'off'
  last_pull_at?: string | null
  last_push_at?: string | null
  profiles?: number
  last_changes?: Record<string, number>
  cvs_pushed?: number
  error?: string | null
}

/** Hard filters on who is ranked after a JD match (the requirements still decide the order). */
export type ResultFilters = {
  locations: string[]
  years_min: number | null
  years_max: number | null
  skills: string[]
  skills_mode: 'all' | 'any'
  domains: string[]
}
export const EMPTY_RESULT_FILTERS: ResultFilters = { locations: [], years_min: null, years_max: null, skills: [], skills_mode: 'all', domains: [] }
export type MatchScope = { sources?: ('file' | 'linkedin')[]; owners?: string[]; filters?: ResultFilters }

export type BulkResult = {
  filename: string
  status: 'added' | 'duplicate' | 'rejected' | 'skipped'
  message: string
  saved_as?: string
  rel_path?: string
}

export type FileState = { state: 'reading' | 'ready' | 'unreadable'; id?: number; name?: string | null }

/** Upload one batch with real upload progress (fetch can't report it; XHR can). */
export function uploadWithProgress(
  files: File[],
  onProgress: (fraction: number) => void,
): Promise<{ added: number; summary: Record<string, number>; results: BulkResult[] }> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f, f.name))
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/cvs')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as never)
      else reject(new ApiError(xhr.status, (body as { detail?: string })?.detail ?? 'Upload failed'))
    }
    xhr.onerror = () => reject(new ApiError(0, 'Could not reach TalentLens. Is it still running?'))
    xhr.send(fd)
  })
}

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

export type UpdateStatus = {
  current: string
  latest: string | null
  update_required: boolean
  checked_at: string | null
  error: string | null
  can_update: boolean
  /** Written by the updater script: starting | updating | done | failed */
  last_run: { state: string; message?: string; from?: string; to?: string; at?: string } | null
}

export const api = {
  health: () => request<Health>('/api/health'),
  updateStatus: (refresh = false) => request<UpdateStatus>(`/api/update${qs({ refresh: refresh || undefined })}`),
  startUpdate: () => request<UpdateStatus & { started: boolean }>('/api/update', { method: 'POST' }),
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
  shortlist: (requirements: Requirements, jd_text: string, limit = 50, rerank = true, scope: MatchScope = {}) =>
    request<ShortlistResult>('/api/shortlist', json({ requirements, jd_text, limit, rerank, ...scope })),
  /** Streams the plain-text explanation; onText gets the full text so far. */
  explainStream: async (cv_id: number, requirements: Requirements, onText: (t: string) => void) => {
    const res = await fetch('/api/shortlist/explain', json({ cv_id, requirements }))
    if (!res.ok || !res.body) {
      let msg = 'Could not explain this match'
      try {
        msg = (await res.json()).detail ?? msg
      } catch {
        /* ignore */
      }
      throw new ApiError(res.status, msg)
    }
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let text = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      text += dec.decode(value, { stream: true })
      onText(text)
    }
    return text
  },
  saveShortlist: (body: { name: string; jd_text: string; requirements: Requirements; results: RankedCV[] }) =>
    request<{ id: number; name: string }>('/api/shortlists', json(body)),
  shortlists: () => request<SavedShortlist[]>('/api/shortlists'),
  getShortlist: (id: number) =>
    request<{ id: number; name: string; created_at: string; jd_text: string; requirements: Requirements; results: RankedCV[] }>(
      `/api/shortlists/${id}`,
    ),
  deleteShortlist: (id: number) => request<void>(`/api/shortlists/${id}`, { method: 'DELETE' }),
  renameShortlist: (id: number, name: string) =>
    request<{ id: number; name: string }>(`/api/shortlists/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  recent: (limit = 6) => request<{ total: number; items: CVSummary[] }>(`/api/cvs${qs({ limit })}`),
  filesStatus: (paths: string[]) => request<Record<string, FileState>>(`/api/cvs/status${qs({ paths })}`),
  settings: () => request<AppSettings>('/api/settings'),
  updateSettings: (
    patch: Partial<{ cv_dir: string; ai_enabled: boolean; ollama_model: string; onboarded: boolean; mongodb_uri: string }>,
  ) =>
    request<AppSettings>('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  checkFolder: (path: string) =>
    request<{ ok: boolean; path?: string; count: number; message: string }>('/api/settings/check-folder', json({ path })),
  pickFolder: () => request<{ path: string | null; cancelled: boolean }>('/api/system/pick-folder', { method: 'POST' }),
  joinTeam: (invite: string) => request<{ ok: boolean; server: string; name: string }>('/api/connections/join', json({ invite })),
  leaveTeam: () => request<{ ok: boolean }>('/api/connections/leave', { method: 'POST' }),
  connectionsStatus: () => request<ConnectionsStatus>('/api/connections/status'),
  syncConnections: (full = false) =>
    request<ConnectionsStatus>(`/api/connections/sync${qs({ full })}`, { method: 'POST' }),
  revealFolder: () => request<{ ok: boolean }>('/api/system/reveal', { method: 'POST' }),
  exportUrl: (id: number) => `/api/shortlists/${id}/export.csv`,
  exportUnsaved: async (body: { name: string; jd_text: string; requirements: Requirements; results: RankedCV[] }) => {
    const res = await fetch('/api/shortlist/export', json(body))
    if (!res.ok) throw new ApiError(res.status, 'Export failed')
    return res.blob()
  },
}
