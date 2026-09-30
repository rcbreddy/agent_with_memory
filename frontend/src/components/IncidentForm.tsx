import { useState, type FormEvent } from 'react'
import type { IncidentInput, Severity } from '../services/api'
import { focusRing, inputCls } from './styles'
import { Card, Field, Spinner } from './ui'

const EMPTY: IncidentInput = {
  title: '',
  service: '',
  environment: 'production',
  severity: 'High',
  symptoms: '',
  error_logs: '',
  recent_changes: '',
  additional_instructions: '',
}

// The two demo incidents from the README, for a quick walkthrough.
const DEMOS: { label: string; data: IncidentInput }[] = [
  {
    label: 'Demo #1',
    data: {
      title: 'Payment API Latency',
      service: 'payment-api',
      environment: 'production',
      severity: 'High',
      symptoms: 'Payment API latency is very high. Payment requests are taking 5-10 seconds.',
      error_logs: 'ERROR RedisConnectionPool: connection pool exhausted (max=50), waited 5000ms for a free connection',
      recent_changes: 'Latest release deployed yesterday.',
      additional_instructions: '',
    },
  },
  {
    label: 'Demo #2',
    data: {
      title: 'Payment requests slow again',
      service: 'payment-api',
      environment: 'production',
      severity: 'High',
      symptoms: 'Payment requests are slow again. p95 latency up to 4s during checkout.',
      error_logs: 'WARN redis.clients: Redis timeout after 2000ms (command GET session:*)',
      recent_changes: 'Traffic increased by 40% after marketing campaign.',
      additional_instructions: '',
    },
  },
]

export default function IncidentForm({ loading, onSubmit }: { loading: boolean; onSubmit: (i: IncidentInput) => void }) {
  const [form, setForm] = useState<IncidentInput>(EMPTY)
  const set = <K extends keyof IncidentInput>(k: K, v: IncidentInput[K]) => setForm((f) => ({ ...f, [k]: v }))

  function submit(e: FormEvent) {
    e.preventDefault()
    onSubmit(form)
  }

  return (
    <Card
      title="New Incident"
      icon={<span className="text-rose-400">●</span>}
      right={
        <div className="flex gap-1">
          {DEMOS.map((d) => (
            <button
              key={d.label}
              type="button"
              onClick={() => setForm(d.data)}
              aria-label={`Fill the form with ${d.label}: ${d.data.title}`}
              className={`rounded border border-slate-600 px-2 py-0.5 text-xs text-slate-300 hover:border-slate-400 hover:text-white ${focusRing}`}
            >
              {d.label}
            </button>
          ))}
        </div>
      }
    >
      <form onSubmit={submit} className="space-y-3" aria-label="New incident">
        <Field label="Incident Title">
          <input className={inputCls} value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="Payment API Latency" required minLength={3} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Service">
            <input className={inputCls} value={form.service} onChange={(e) => set('service', e.target.value)} placeholder="payment-api" required pattern="[A-Za-z0-9._/\-]+" title="letters, digits, . _ / -" />
          </Field>
          <Field label="Environment">
            <select className={inputCls} value={form.environment} onChange={(e) => set('environment', e.target.value)}>
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="development">development</option>
            </select>
          </Field>
          <Field label="Severity">
            <select className={inputCls} value={form.severity} onChange={(e) => set('severity', e.target.value as Severity)}>
              {['Low', 'Medium', 'High', 'Critical'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Symptoms">
          <textarea className={inputCls} rows={3} value={form.symptoms} onChange={(e) => set('symptoms', e.target.value)} placeholder="Payment requests are taking 5–10 seconds." required minLength={3} />
        </Field>
        <Field label="Error Logs">
          <textarea className={`${inputCls} font-mono text-xs`} rows={3} value={form.error_logs} onChange={(e) => set('error_logs', e.target.value)} placeholder="Redis connection pool exhausted." />
        </Field>
        <Field label="Recent Changes">
          <textarea className={inputCls} rows={2} value={form.recent_changes} onChange={(e) => set('recent_changes', e.target.value)} placeholder="Traffic increased after the latest release." />
        </Field>
        <Field label="Additional Instructions" hint="“From now on …” is remembered as a lasting preference; one-off requests apply to this report only.">
          <textarea className={inputCls} rows={3} value={form.additional_instructions} onChange={(e) => set('additional_instructions', e.target.value)} placeholder="Add instructions for the AI agent..." maxLength={2000} />
        </Field>
        <button
          type="submit"
          disabled={loading}
          aria-busy={loading}
          className={`flex w-full items-center justify-center gap-2 rounded-md bg-sky-700 py-2.5 text-sm font-semibold text-white hover:bg-sky-600 disabled:opacity-60 ${focusRing}`}
        >
          {loading ? (
            <>
              <Spinner /> Recalling memory &amp; analyzing…
            </>
          ) : (
            'Analyze Incident'
          )}
        </button>
      </form>
    </Card>
  )
}
