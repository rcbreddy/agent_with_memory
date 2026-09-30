// Shared style tokens and tone helpers (kept out of ui.tsx so that file only exports components).

export const tones = {
  slate: 'bg-slate-700/40 text-slate-200 ring-slate-500/40',
  green: 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/40',
  amber: 'bg-amber-500/10 text-amber-200 ring-amber-500/40',
  red: 'bg-rose-500/10 text-rose-200 ring-rose-500/40',
  sky: 'bg-sky-500/10 text-sky-200 ring-sky-500/40',
  violet: 'bg-violet-500/10 text-violet-200 ring-violet-500/40',
}
export type Tone = keyof typeof tones

export const severityTone = (s: string | null | undefined): Tone =>
  s === 'Critical' ? 'red' : s === 'High' ? 'amber' : s === 'Medium' ? 'sky' : 'slate'

export const focusRing = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400'

export const inputCls = `w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-400 ${focusRing}`
