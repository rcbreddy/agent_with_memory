import { useLearningStatus } from '../hooks/useLearningStatus'
import type { AutoMemoryResult, PreferenceResult } from '../services/api'
import type { Tone } from './styles'
import { Badge, Card, SectionHeading, Spinner } from './ui'

const STATUS: Record<AutoMemoryResult['status'], { tone: Tone; label: string }> = {
  pending: { tone: 'sky', label: 'Learning from this incident…' },
  stored: { tone: 'violet', label: 'Retained as hypothesis' },
  skipped: { tone: 'slate', label: 'Nothing new to retain' },
  error: { tone: 'red', label: '⚠ Not retained' },
}

const ACTION_LABEL = { added: 'Added', updated: 'Updated', removed: 'Removed', learned: 'Learned from repetition' }

export default function LearningPanel({ incidentId, memory, preferences, onSettled }: {
  incidentId: string
  memory: AutoMemoryResult
  preferences: PreferenceResult
  onSettled?: () => void
}) {
  const learning = useLearningStatus(incidentId, memory, onSettled)
  const status = STATUS[learning.status]

  return (
    <Card title="3 · Learn — what the agent remembers" icon={<span className="text-violet-400">✦</span>} right={<Badge tone={status.tone}>{status.label}</Badge>}>
      <div className="space-y-5">
        <div aria-live="polite" aria-busy={learning.status === 'pending'}>
          <SectionHeading>Incident memory — automatically extracted knowledge (Hindsight retain)</SectionHeading>
          <p className="flex items-center gap-2 text-sm text-slate-200">
            {learning.status === 'pending' && <Spinner />}
            {learning.message}
          </p>
          {learning.items.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm text-slate-200">
              {learning.items.map((item, i) => (
                <li key={i} className="rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 px-3 py-2">
                  <span className="mr-2 text-xs font-semibold uppercase text-amber-200">{item.category.replaceAll('_', ' ')}</span>
                  {item.content}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-slate-400">
            Analysis findings are stored as <strong>unconfirmed hypotheses</strong>. Confirming the real resolution below stores trusted knowledge that
            outranks them. Raw logs and secrets are never stored.
          </p>
        </div>

        <div>
          <SectionHeading>User preference memory — kept separate from incident knowledge</SectionHeading>
          <p className={`text-sm ${preferences.status === 'error' ? 'text-rose-200' : 'text-slate-200'}`}>{preferences.message}</p>
          {preferences.applied.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-sm text-slate-300">
              {preferences.applied.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {preferences.changes.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {preferences.changes.map((c) => (
                <li key={`${c.action}-${c.key}`} className="text-slate-200">
                  <Badge tone={c.action === 'removed' ? 'slate' : 'violet'}>{ACTION_LABEL[c.action]}</Badge> {c.preference}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  )
}
