import { useState, type FormEvent } from 'react'
import { api, type ResolutionInput, type ResolveResponse } from '../services/api'
import { focusRing, inputCls } from './styles'
import { Card, ErrorBox, Field, Spinner } from './ui'

type Step = 'ask' | 'form' | 'later' | 'saved'

const EMPTY: ResolutionInput = { root_cause: '', solution: '', outcome: '', failed_approaches: '', notes: '' }
const secondaryBtn = `rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 ${focusRing}`

export default function ResolutionPanel({ incidentId, onSaved }: { incidentId: string; onSaved: () => void }) {
  const [step, setStep] = useState<Step>('ask')
  const [form, setForm] = useState<ResolutionInput>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<ResolveResponse | null>(null)
  const set = (k: keyof ResolutionInput, v: string) => setForm((f) => ({ ...f, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      setSaved(await api.resolve(incidentId, form))
      setStep('saved')
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="4 · Confirm & Retain — resolution" icon={<span className="text-emerald-400">✓</span>}>
      {step === 'ask' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-100">Was the incident resolved? Confirmed resolutions become trusted memory.</p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setStep('form')} className={`rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 ${focusRing}`}>
              Yes, save resolution
            </button>
            <button type="button" onClick={() => setStep('later')} className={secondaryBtn}>
              Not yet
            </button>
          </div>
        </div>
      )}

      {step === 'later' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-300">
            OK. Only the analysis’ unconfirmed hypotheses are in memory. Come back when it’s fixed to store the confirmed resolution.
          </p>
          <button type="button" onClick={() => setStep('form')} className={secondaryBtn}>
            It’s resolved now
          </button>
        </div>
      )}

      {step === 'form' && (
        <form onSubmit={submit} className="space-y-3" aria-describedby="resolution-help">
          <p id="resolution-help" className="text-xs text-slate-400">
            Record what actually happened. Secrets and credentials are redacted before anything is stored.
          </p>
          <Field label="Actual root cause (required)">
            <input className={inputCls} value={form.root_cause} onChange={(e) => set('root_cause', e.target.value)} placeholder="Redis connection pool exhaustion" required minLength={3} />
          </Field>
          <Field label="Actual solution (required)">
            <textarea className={inputCls} rows={2} value={form.solution} onChange={(e) => set('solution', e.target.value)} placeholder="Increased Redis connection pool from 50 to 150." required minLength={3} />
          </Field>
          <Field label="Outcome (required)">
            <input className={inputCls} value={form.outcome} onChange={(e) => set('outcome', e.target.value)} placeholder="API latency returned to normal." required minLength={3} />
          </Field>
          <Field label="What didn’t work (optional)">
            <input className={inputCls} value={form.failed_approaches} onChange={(e) => set('failed_approaches', e.target.value)} placeholder="Restarting payment-api pods only helped for ~10 minutes." />
          </Field>
          <Field label="Lessons learned (optional)">
            <textarea className={inputCls} rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Add an alert on Redis pool utilisation > 80%." />
          </Field>
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className="flex gap-2">
            <button type="submit" disabled={saving} aria-busy={saving} className={`flex items-center gap-2 rounded-md bg-violet-700 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-600 disabled:opacity-60 ${focusRing}`}>
              {saving ? <><Spinner /> Saving to Hindsight…</> : 'Save to Hindsight'}
            </button>
            <button type="button" onClick={() => setStep('ask')} className={`rounded-md px-3 py-2 text-sm text-slate-300 hover:text-white ${focusRing}`}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {step === 'saved' && saved && (
        <div className="space-y-3">
          <div role="status" className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            ✓ {saved.message}
            {saved.retain_ms != null && <span className="ml-1 text-emerald-200/80">({Math.round(saved.retain_ms)} ms)</span>}
          </div>
          <details>
            <summary className={`cursor-pointer text-xs text-slate-400 hover:text-slate-200 ${focusRing}`}>Knowledge retained in Hindsight</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-300">{saved.memory_document}</pre>
          </details>
        </div>
      )}
    </Card>
  )
}
