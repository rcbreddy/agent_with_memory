// Thin, typed client for the FastAPI backend. The browser only ever talks to FastAPI:
// Groq and Hindsight keys never reach the frontend. Only a session token is stored here.

export type Severity = 'Low' | 'Medium' | 'High' | 'Critical'
export type Level = 'Low' | 'Medium' | 'High'

export interface IncidentInput {
  title: string
  service: string
  environment: string
  severity: Severity
  symptoms: string
  error_logs: string
  recent_changes: string
  additional_instructions: string
}

export interface RecalledFact {
  text: string
  type: string | null
  score: number | null
}

export interface RecalledIncident {
  incident_id: string | null
  title: string | null
  service: string | null
  environment: string | null
  severity: string | null
  root_cause: string | null
  solution: string | null
  outcome: string | null
  failed_approaches: string | null
  error_signature: string | null
  recent_changes: string | null
  resolved_at: string | null
  relevance_score: number | null
  /** true = confirmed by an engineer; false = auto-extracted, unconfirmed hypothesis */
  confirmed: boolean
  why_relevant: string[]
  facts: RecalledFact[]
}

export interface RecallResult {
  status: 'ok' | 'empty' | 'error'
  message: string
  query: string
  memories: RecalledIncident[]
  other_facts: RecalledFact[]
}

export interface IncidentAnalysis {
  summary: string
  possible_causes: { cause: string; likelihood: Level; evidence: string }[]
  historical_matches: { incident: string; similarities: string[]; differences: string[]; how_it_applies: string }[]
  recommended_checks: string[]
  recommended_solution: string
  confidence: Level
  confidence_reason: string
}

export interface AutoMemoryResult {
  status: 'pending' | 'stored' | 'skipped' | 'error'
  message: string
  items: { category: string; content: string }[]
  timings_ms: Record<string, number>
}

export interface PreferenceResult {
  status: 'ok' | 'error'
  message: string
  applied: string[]
  changes: { action: 'added' | 'updated' | 'removed' | 'learned'; key: string; preference: string }[]
}

export interface AnalysisMetrics {
  total_ms: number
  stages_ms: Record<string, number>
  memories_recalled: number
  facts_in_prompt: number
  prompt_chars: number
  prompt_tokens: number | null
  completion_tokens: number | null
}

export interface AnalyzeResponse {
  incident_id: string
  analysis: IncidentAnalysis
  recall: RecallResult
  model: string
  memory: AutoMemoryResult
  preferences: PreferenceResult
  metrics: AnalysisMetrics | null
}

export interface ResolutionInput {
  root_cause: string
  solution: string
  outcome: string
  failed_approaches: string
  notes: string
}

export interface ResolveResponse {
  incident_id: string
  retained: boolean
  message: string
  memory_document: string
  retain_ms: number | null
}

export interface IncidentSummary {
  id: string
  title: string
  service: string
  environment: string
  severity: Severity
  status: 'analyzed' | 'resolved'
  created_at: string
  root_cause: string | null
  outcome: string | null
  resolved_at: string | null
  retained_in_hindsight: boolean
}

export interface HindsightStatus {
  ok: boolean
  detail: string
  memory_units?: number | null
}

export interface Health {
  groq: { configured: boolean; model: string }
  hindsight: HindsightStatus
  hindsight_configured: boolean
}

export interface AuthResponse {
  token: string
  user_id: string
  username: string
}

export interface Me {
  user_id: string
  username: string
  hindsight: HindsightStatus
  preferences: string[] | null
}

export interface IncidentMemories {
  incident_id: string
  recall: RecallResult | null
  groq_prompt: string | null
}

// ---------------------------------------------------------------- session

const SESSION_KEY = 'ira_session'
const LEGACY_KEYS = ['ira_token', 'ira_user']

export interface SessionUser {
  token: string
  user_id: string
  username: string
}

export const session = {
  get current(): SessionUser | null {
    try {
      const raw = localStorage.getItem(SESSION_KEY)
      const s = raw ? (JSON.parse(raw) as SessionUser) : null
      return s?.token && s.user_id ? s : null
    } catch {
      return null
    }
  },
  get token() {
    return this.current?.token ?? null
  },
  set(auth: AuthResponse) {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ token: auth.token, user_id: auth.user_id, username: auth.username }))
  },
  clear() {
    localStorage.removeItem(SESSION_KEY)
    LEGACY_KEYS.forEach((k) => localStorage.removeItem(k))
  },
}

// ---------------------------------------------------------------- transport

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// In development the Vite proxy forwards /api to the local FastAPI (same origin).
// Production builds use VITE_API_URL, falling back to the deployed backend.
const DEFAULT_PROD_API = 'https://agent-with-memory-1.onrender.com'
export const API_BASE = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? '' : DEFAULT_PROD_API)).replace(/\/+$/, '')

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

const AUTH_PATHS = ['/api/auth/login', '/api/auth/register']

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail))
      return body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join('; ')
  } catch {
    /* non-JSON error body */
  }
  return `Request failed (${res.status})`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const token = session.token
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the backend. Check your connection and try again.')
  }
  if (res.status === 401 && !AUTH_PATHS.includes(path)) {
    session.clear()
    onUnauthorized()
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const incidentPath = (id: string, suffix = '') => `/api/incidents/${encodeURIComponent(id)}${suffix}`

export const api = {
  login: (username: string, password: string) => post<AuthResponse>('/api/auth/login', { username, password }),
  register: (username: string, password: string) => post<AuthResponse>('/api/auth/register', { username, password }),
  me: () => request<Me>('/api/auth/me'),
  logout: () => post<void>('/api/auth/logout'),
  health: () => request<Health>('/api/health'),
  analyze: (incident: IncidentInput) => post<AnalyzeResponse>('/api/incidents/analyze', incident),
  resolve: (id: string, resolution: ResolutionInput) => post<ResolveResponse>(incidentPath(id, '/resolve'), resolution),
  list: () => request<IncidentSummary[]>('/api/incidents'),
  learning: (id: string) => request<AutoMemoryResult>(incidentPath(id, '/learning')),
  memories: (id: string) => request<IncidentMemories>(incidentPath(id, '/memories')),
}
