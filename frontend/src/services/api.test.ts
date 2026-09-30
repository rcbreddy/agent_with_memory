import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, session, setUnauthorizedHandler } from './api'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('sends the bearer token and no JSON content-type on GET', async () => {
    session.set({ token: 'tok', user_id: 'u1', username: 'alice' })
    const fetchMock = vi.fn().mockResolvedValue(json(200, []))
    vi.stubGlobal('fetch', fetchMock)
    await api.list()
    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer tok')
    expect(headers.get('Content-Type')).toBeNull()
  })

  it('clears the session and notifies the app on 401', async () => {
    session.set({ token: 'expired', user_id: 'u1', username: 'alice' })
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(401, { detail: 'Session expired, please log in again' })))
    await expect(api.list()).rejects.toThrow('Session expired')
    expect(session.current).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('does not treat a failed login as an expired session', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(401, { detail: 'Invalid username or password' })))
    await expect(api.login('a', 'b')).rejects.toThrow('Invalid username or password')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('turns FastAPI validation errors into a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(422, { detail: [{ loc: ['body', 'service'], msg: 'String should match pattern' }] })))
    await expect(api.list()).rejects.toThrow('service: String should match pattern')
  })

  it('reports an unreachable backend without leaking internals', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await api.health().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).message).toMatch(/Cannot reach the backend/)
  })
})

describe('frontend security boundary', () => {
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => {
      const p = join(dir, f)
      return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) ? [p] : []
    })

  it('never calls Groq or Hindsight directly and reads no secret-looking env vars', () => {
    for (const file of files(join(process.cwd(), 'src'))) {
      const src = readFileSync(file, 'utf8')
      expect(src, file).not.toMatch(/api\.groq\.com|hindsight\.vectorize\.io/)
      expect(src, file).not.toMatch(/VITE_[A-Z_]*(KEY|SECRET|TOKEN|PASSWORD)/)
    }
  })
})
