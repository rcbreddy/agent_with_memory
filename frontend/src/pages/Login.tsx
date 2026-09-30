import { useState, type FormEvent } from 'react'
import { focusRing, inputCls } from '../components/styles'
import { api, session, type SessionUser } from '../services/api'

type Mode = 'login' | 'register'

export default function Login({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = mode === 'login' ? await api.login(username, password) : await api.register(username, password)
      session.clear() // never carry anything over from a previous account
      session.set(res)
      onLogin({ token: res.token, user_id: res.user_id, username: res.username })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  const register = mode === 'register'

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} aria-labelledby="login-title" className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <div aria-hidden="true" className="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-500/15 text-xl text-rose-400">⚠</div>
          <div>
            <h1 id="login-title" className="text-lg font-semibold text-white">Incident Response Agent</h1>
            <p className="text-xs text-slate-300">Learns from past incidents with Hindsight memory</p>
          </div>
        </div>

        <div role="group" aria-label="Choose sign in or create account" className="mb-5 grid grid-cols-2 rounded-md bg-slate-950 p-1 text-sm">
          {(['login', 'register'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => switchMode(m)}
              className={`rounded py-1.5 ${focusRing} ${mode === m ? 'bg-slate-700 text-white' : 'text-slate-300 hover:text-white'}`}
            >
              {m === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        <label htmlFor="username" className="mb-1 block text-xs font-medium text-slate-300">Username</label>
        <input
          id="username"
          className={`${inputCls} mb-4`}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          {...(register && { minLength: 3, maxLength: 32, pattern: '[A-Za-z0-9_.\\-]+', title: '3-32 letters, digits, . _ -' })}
        />
        <label htmlFor="password" className="mb-1 block text-xs font-medium text-slate-300">Password</label>
        <input
          id="password"
          type="password"
          className={`${inputCls} mb-4`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={register ? 'new-password' : 'current-password'}
          aria-describedby={register ? 'password-help' : undefined}
          required
          minLength={register ? 8 : undefined}
        />
        {register && (
          <p id="password-help" className="-mt-2 mb-4 text-xs text-slate-400">
            At least 8 characters. You get your own private incident history and Hindsight memory.
          </p>
        )}
        {error && (
          <p role="alert" className="mb-4 rounded-md bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          aria-busy={loading}
          className={`w-full rounded-md bg-sky-700 py-2 text-sm font-medium text-white hover:bg-sky-600 disabled:opacity-50 ${focusRing}`}
        >
          {loading ? 'Please wait…' : register ? 'Create account' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
