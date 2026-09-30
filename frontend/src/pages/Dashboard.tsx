import { useCallback, useEffect, useState } from 'react'
import AnalysisPanel from '../components/AnalysisPanel'
import HistoryTable from '../components/HistoryTable'
import IncidentForm from '../components/IncidentForm'
import LearningPanel from '../components/LearningPanel'
import MemoryPanel from '../components/MemoryPanel'
import ResolutionPanel from '../components/ResolutionPanel'
import { focusRing } from '../components/styles'
import { Badge, ErrorBox } from '../components/ui'
import { api, session, type AnalyzeResponse, type Health, type IncidentInput, type IncidentSummary, type Me } from '../services/api'

// The agent's learning loop, shown as a progress indicator.
const LOOP = ['Recall', 'Reason', 'Learn', 'Confirm', 'Retain → Reuse']

function LoopProgress({ done, active }: { done: number; active: number }) {
  return (
    <ol aria-label="Agent learning loop" className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-6 pb-3 text-xs">
      {LOOP.map((label, i) => {
        const state = i < done ? 'done' : i === active ? 'current' : 'todo'
        const cls = state === 'done' ? 'bg-emerald-500/15 text-emerald-200' : state === 'current' ? 'bg-sky-500/20 text-sky-100' : 'bg-slate-800 text-slate-300'
        return (
          <li key={label} className="flex items-center gap-2" aria-current={state === 'current' ? 'step' : undefined}>
            <span className={`rounded-full px-2.5 py-1 ${cls}`}>
              {state === 'done' ? '✓ ' : ''}
              {i + 1}. {label}
              <span className="sr-only"> ({state === 'todo' ? 'not started' : state === 'current' ? 'in progress' : 'done'})</span>
            </span>
            {i < LOOP.length - 1 && <span aria-hidden="true" className="text-slate-500">→</span>}
          </li>
        )
      })}
    </ol>
  )
}

function ServiceBadges({ health, me }: { health: Health; me: Me | null }) {
  const memoryOk = health.hindsight.ok && me?.hindsight.ok !== false
  const units = me?.hindsight.memory_units
  return (
    <>
      <Badge tone={memoryOk ? 'violet' : 'red'}>
        Hindsight {!memoryOk ? '· ⚠ unavailable' : units != null ? `· your memory: ${units} units` : '· connected'}
      </Badge>
      <Badge tone={health.groq.configured ? 'sky' : 'red'}>
        Groq {health.groq.configured ? `· ${health.groq.model}` : '· ⚠ not configured'}
      </Badge>
    </>
  )
}

export default function Dashboard({ user, onLogout }: { user: string; onLogout: () => void }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [incidents, setIncidents] = useState<IncidentSummary[]>([])
  const [result, setResult] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retained, setRetained] = useState(false)

  // Both are scoped server-side to the authenticated user.
  const refreshHistory = useCallback(() => api.list().then(setIncidents).catch(() => {}), [])
  const refreshMemoryStats = useCallback(() => api.me().then(setMe).catch(() => {}), [])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    refreshHistory()
    refreshMemoryStats()
  }, [refreshHistory, refreshMemoryStats])

  async function analyze(input: IncidentInput) {
    setLoading(true)
    setError(null)
    setResult(null)
    setRetained(false)
    try {
      setResult(await api.analyze(input))
      refreshHistory()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function logout() {
    await api.logout().catch(() => {})
    session.clear()
    onLogout()
  }

  const done = !result ? 0 : retained ? LOOP.length : 3
  const active = loading ? 0 : result && !retained ? 3 : -1
  const status = loading
    ? 'Recalling similar incidents from Hindsight and analyzing with Groq…'
    : error
      ? ''
      : result
        ? `Analysis ready for ${result.incident_id}. ${result.recall.message}`
        : ''

  return (
    <div className="min-h-screen">
      <a href="#main" className={`sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:rounded focus:bg-slate-800 focus:px-3 focus:py-2 ${focusRing}`}>
        Skip to content
      </a>
      <header className="border-b border-slate-800 bg-slate-900/80">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <div aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-lg bg-rose-500/15 text-rose-400">⚠</div>
            <div>
              <h1 className="text-lg font-semibold text-white">Incident Response Agent</h1>
              <p className="text-xs text-slate-300">Learns from past incidents with Hindsight · reasons with Groq</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {health && <ServiceBadges health={health} me={me} />}
            <span className="ml-2 text-sm text-slate-300">Signed in as {user}</span>
            <button type="button" onClick={logout} className={`rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800 ${focusRing}`}>
              Log out
            </button>
          </div>
        </div>
        <LoopProgress done={done} active={active} />
      </header>

      <p role="status" aria-live="polite" className="sr-only">{status}</p>

      {health && !health.hindsight.ok && (
        <div className="mx-auto max-w-7xl px-6 pt-4">
          <ErrorBox>Hindsight is not reachable ({health.hindsight.detail}). Analyses will run without historical memory.</ErrorBox>
        </div>
      )}

      <main id="main" className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[420px_1fr]">
        <div className="space-y-6">
          <IncidentForm loading={loading} onSubmit={analyze} />
        </div>
        <div className="space-y-6">
          {error && <ErrorBox>{error}</ErrorBox>}
          {!result && !error && (
            <div className="flex h-full min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-700 p-10 text-center text-sm text-slate-300">
              {loading
                ? 'Recalling similar incidents from Hindsight, then asking Groq to analyze…'
                : 'Describe an incident and choose “Analyze Incident”. The agent first recalls relevant past incidents from your Hindsight memory.'}
            </div>
          )}
          {result && (
            <>
              <MemoryPanel recall={result.recall} />
              <AnalysisPanel result={result} />
              <LearningPanel
                key={`learn-${result.incident_id}`}
                incidentId={result.incident_id}
                memory={result.memory}
                preferences={result.preferences}
                onSettled={refreshMemoryStats}
              />
              <ResolutionPanel
                key={result.incident_id}
                incidentId={result.incident_id}
                onSaved={() => {
                  setRetained(true)
                  refreshHistory()
                  refreshMemoryStats()
                }}
              />
            </>
          )}
        </div>
      </main>

      <div className="mx-auto max-w-7xl px-6 pb-10">
        <HistoryTable incidents={incidents} />
      </div>
    </div>
  )
}
