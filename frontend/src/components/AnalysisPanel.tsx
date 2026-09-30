import { useState } from 'react'
import { api, type AnalysisMetrics, type AnalyzeResponse, type Level } from '../services/api'
import { focusRing, type Tone } from './styles'
import { Badge, Card, SectionHeading } from './ui'

const likelihoodTone = (l: Level): Tone => (l === 'High' ? 'red' : l === 'Medium' ? 'amber' : 'slate')
const confidenceTone = (c: Level): Tone => (c === 'High' ? 'green' : c === 'Medium' ? 'amber' : 'red')

const STAGE_LABELS: Record<string, string> = {
  hindsight_recall: 'Hindsight recall',
  preferences_load: 'Preference recall (parallel)',
  groq_analysis: 'Groq reasoning',
  preference_learning: 'Preference learning (parallel)',
  db_write: 'Database write',
}

function formatMs(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`
}

function MetricsDetails({ metrics }: { metrics: AnalysisMetrics }) {
  return (
    <details className="text-xs text-slate-300">
      <summary className={`cursor-pointer text-slate-400 hover:text-slate-200 ${focusRing}`}>
        Latency: {formatMs(metrics.total_ms)} · {metrics.memories_recalled} memories · {metrics.prompt_tokens ?? '?'} prompt tokens
      </summary>
      <table className="mt-2 w-full max-w-sm text-left">
        <caption className="sr-only">Per-stage latency of this analysis</caption>
        <tbody>
          {Object.entries(metrics.stages_ms).map(([stage, ms]) => (
            <tr key={stage}>
              <th scope="row" className="py-0.5 pr-4 font-normal text-slate-400">{STAGE_LABELS[stage] ?? stage}</th>
              <td className="py-0.5 tabular-nums">{formatMs(ms)}</td>
            </tr>
          ))}
          <tr>
            <th scope="row" className="py-0.5 pr-4 font-normal text-slate-400">Facts sent to Groq</th>
            <td className="py-0.5 tabular-nums">{metrics.facts_in_prompt}</td>
          </tr>
          <tr>
            <th scope="row" className="py-0.5 pr-4 font-normal text-slate-400">Completion tokens</th>
            <td className="py-0.5 tabular-nums">{metrics.completion_tokens ?? '?'}</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-1 text-slate-400">Memory extraction and retention run after the response, so they add no wait.</p>
    </details>
  )
}

function PromptViewer({ incidentId }: { incidentId: string }) {
  const [prompt, setPrompt] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    if (prompt !== null) return setPrompt(null)
    setLoading(true)
    setError(null)
    try {
      setPrompt((await api.memories(incidentId)).groq_prompt ?? '')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={prompt !== null}
        disabled={loading}
        className={`text-xs text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline ${focusRing}`}
      >
        {loading ? 'Loading prompt…' : prompt === null ? 'Show exact prompt sent to Groq (current incident + Hindsight memory)' : 'Hide prompt'}
      </button>
      {error && <p role="alert" className="mt-2 text-xs text-rose-200">Could not load the prompt: {error}</p>}
      {prompt !== null && (
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-300">{prompt}</pre>
      )}
    </div>
  )
}

export default function AnalysisPanel({ result }: { result: AnalyzeResponse }) {
  const a = result.analysis
  return (
    <Card
      title="2 · Reason — AI Analysis"
      icon={<span className="text-sky-400">▲</span>}
      right={
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{result.incident_id}</Badge>
          <Badge tone="sky">Groq · {result.model}</Badge>
        </div>
      }
    >
      <div className="space-y-6">
        <div>
          <SectionHeading>Summary</SectionHeading>
          <p className="text-sm leading-relaxed text-slate-100">{a.summary}</p>
        </div>

        <div>
          <SectionHeading>Possible causes</SectionHeading>
          <ul className="space-y-2">
            {a.possible_causes.map((c, i) => (
              <li key={i} className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-white">{c.cause}</span>
                  <Badge tone={likelihoodTone(c.likelihood)}>{c.likelihood} likelihood</Badge>
                </div>
                {c.evidence && <p className="mt-1 text-xs text-slate-300">{c.evidence}</p>}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <SectionHeading>Compared with past incidents</SectionHeading>
          {a.historical_matches.length === 0 ? (
            <p className="text-sm text-slate-400">No historical incidents were used for this analysis.</p>
          ) : (
            <ul className="space-y-3">
              {a.historical_matches.map((m, i) => (
                <li key={i} className="rounded-md border border-violet-500/30 bg-violet-500/5 p-3 text-sm">
                  <div className="mb-2 font-medium text-violet-100">{m.incident}</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <h4 className="text-[11px] font-semibold uppercase text-emerald-300">Similarities</h4>
                      <ul className="list-inside list-disc text-slate-200">{m.similarities.map((s, j) => <li key={j}>{s}</li>)}</ul>
                    </div>
                    <div>
                      <h4 className="text-[11px] font-semibold uppercase text-amber-300">Differences</h4>
                      <ul className="list-inside list-disc text-slate-200">{m.differences.map((s, j) => <li key={j}>{s}</li>)}</ul>
                    </div>
                  </div>
                  {m.how_it_applies && (
                    <p className="mt-2 text-slate-200"><span className="text-slate-400">How it applies now: </span>{m.how_it_applies}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <SectionHeading>Recommended checks</SectionHeading>
          <ol className="list-inside list-decimal space-y-1 text-sm text-slate-100">
            {a.recommended_checks.map((c, i) => <li key={i}>{c}</li>)}
          </ol>
        </div>

        <div>
          <SectionHeading>Recommended solution</SectionHeading>
          <p className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm leading-relaxed text-emerald-50">{a.recommended_solution}</p>
        </div>

        <div>
          <SectionHeading>Confidence</SectionHeading>
          <div className="flex items-center gap-3">
            <Badge tone={confidenceTone(a.confidence)}>{a.confidence} confidence</Badge>
            <span className="text-sm text-slate-300">{a.confidence_reason}</span>
          </div>
        </div>

        <div className="space-y-2 border-t border-slate-800 pt-4">
          {result.metrics && <MetricsDetails metrics={result.metrics} />}
          <PromptViewer incidentId={result.incident_id} />
        </div>
      </div>
    </Card>
  )
}
