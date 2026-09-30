import { useId, type ReactNode } from 'react'
import { tones, type Tone } from './styles'

export function Card({ title, icon, right, children, className = '' }: {
  title: string
  icon?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className={`rounded-xl border border-slate-800 bg-slate-900/70 ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-3">
        <h2 id={headingId} className="flex items-center gap-2 text-sm font-semibold tracking-wide text-white">
          {icon && <span aria-hidden="true">{icon}</span>}
          {title}
        </h2>
        {right}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

/** Status is always spelled out in text; colour is only a secondary cue. */
export function Badge({ tone = 'slate', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-400">{hint}</span>}
    </label>
  )
}

export function Spinner() {
  return <span aria-hidden="true" className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
      <span className="font-semibold">Error: </span>
      {children}
    </div>
  )
}

export function SectionHeading({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{children}</h3>
}
