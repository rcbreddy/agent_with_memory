import type { RecalledIncident, RecallResult } from '../services/api'
import { severityTone } from './styles'
import { Badge, Card } from './ui'

function Row({ label, value, tone }: { label: string; value: string | null; tone?: string }) {
  if (!value) return null
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</dt>
      <dd className={`text-sm ${tone ?? 'text-slate-200'}`}>{value}</dd>
    </div>
  )
}

export function TrustBadge({ confirmed }: { confirmed: boolean }) {
  return confirmed ? (
    <Badge tone="green" title="An engineer confirmed this root cause and fix when resolving the incident.">
      ✓ CONFIRMED · Confirmed resolution
    </Badge>
  ) : (
    <Badge tone="amber" title="Auto-extracted from an earlier analysis; never confirmed by a resolution.">
      ⚠ UNCONFIRMED · Unconfirmed hypothesis
    </Badge>
  )
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function StatusBadge({ recall }: { recall: RecallResult }) {
  if (recall.status === 'ok') {
    const n = recall.memories.length
    return <Badge tone="violet">{plural(n, 'relevant historical incident')}</Badge>
  }
  if (recall.status === 'empty') return <Badge tone="slate">No relevant memory</Badge>
  return <Badge tone="red">⚠ Memory unavailable</Badge>
}

function RecalledIncidentCard({ m }: { m: RecalledIncident }) {
  const heading = [m.service, m.environment].filter(Boolean).join(' — ')
  return (
    <article
      aria-label={`${m.confirmed ? 'Confirmed' : 'Unconfirmed'} historical incident ${m.incident_id ?? ''}: ${m.title ?? 'recalled incident'}`}
      className={`rounded-lg border p-4 ${m.confirmed ? 'border-violet-500/30 bg-violet-500/5' : 'border-dashed border-amber-500/40 bg-amber-500/5'}`}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <TrustBadge confirmed={m.confirmed} />
        {m.incident_id && <Badge>{m.incident_id}</Badge>}
        {m.severity && <Badge tone={severityTone(m.severity)}>{m.severity}</Badge>}
        {m.resolved_at && <span className="text-xs text-slate-400">resolved {new Date(m.resolved_at).toLocaleString()}</span>}
      </div>
      {heading && <p className="text-xs font-medium uppercase tracking-wider text-sky-300">{heading}</p>}
      <h3 className="mb-3 font-semibold text-white">{m.title ?? 'Recalled incident'}</h3>
      {!m.confirmed && (
        <p className="mb-3 text-xs text-amber-100">This finding has not been confirmed by a resolution. Treat it as a hypothesis to verify.</p>
      )}
      <dl className="grid gap-3 sm:grid-cols-2">
        <Row label={m.confirmed ? 'Confirmed root cause' : 'Possible cause'} value={m.root_cause} tone="text-amber-100" />
        <Row label={m.confirmed ? 'Previous resolution' : 'Recommended fix (not confirmed)'} value={m.solution} tone="text-emerald-100" />
        <Row label="Outcome" value={m.outcome} />
        <Row label="Failed approach — did not work" value={m.failed_approaches} tone="text-rose-100" />
        <Row label="Error signature then" value={m.error_signature} />
        <Row label="Recent changes then" value={m.recent_changes} />
      </dl>
      {m.why_relevant.length > 0 && (
        <div className="mt-3 rounded-md bg-slate-950/60 p-3">
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Why relevant</h4>
          <ul className="list-inside list-disc text-sm text-slate-200">
            {m.why_relevant.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {m.facts.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-200">
            {plural(m.facts.length, 'fact')} recalled by Hindsight
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-slate-300">
            {m.facts.map((f, j) => (
              <li key={j}>
                <span className="text-slate-400">[{f.type}]</span> {f.text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  )
}

export default function MemoryPanel({ recall }: { recall: RecallResult }) {
  const tone = recall.status === 'error' ? 'text-rose-200' : recall.status === 'ok' ? 'text-violet-100' : 'text-slate-300'
  const confirmed = recall.memories.filter((m) => m.confirmed).length
  return (
    <Card title="1 · Recall — Hindsight Memory" icon={<span className="text-violet-400">◆</span>} right={<StatusBadge recall={recall} />} className="border-violet-500/30">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-violet-300">Persistent incident memory recalled from your private Hindsight bank</p>
      <p className={`mb-3 text-sm ${tone}`} role={recall.status === 'error' ? 'alert' : undefined}>
        {recall.message}
        {recall.status === 'empty' && ' Once you confirm this incident’s resolution, the agent will remember it.'}
      </p>
      {recall.status === 'ok' && (
        <p className="mb-4 rounded-md border border-slate-700 bg-slate-950/60 px-3 py-2 text-xs text-slate-300">
          <strong className="text-slate-100">Historical memory is evidence, not the answer.</strong> The agent compares these incidents
          with the current one and explains what is different before recommending anything.
          {recall.memories.length > 0 && ` ${confirmed} confirmed, ${recall.memories.length - confirmed} unconfirmed.`}
        </p>
      )}
      <div className="space-y-4">
        {recall.memories.map((m, i) => (
          <RecalledIncidentCard key={m.incident_id ?? i} m={m} />
        ))}
        {recall.other_facts.length > 0 && (
          <div className="rounded-lg border border-slate-800 p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Other related knowledge</h3>
            <ul className="list-inside list-disc space-y-1 text-sm text-slate-200">
              {recall.other_facts.map((f, i) => (
                <li key={i}>{f.text}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
