import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError, session } from '../services/api'
import Login from './Login'

describe('Login', () => {
  it('has labelled fields and announces errors', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(new ApiError(401, 'Invalid username or password'))
    render(<Login onLogin={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Username'), 'alice')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-pass')
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign in' }).at(-1)!) // the submit button, not the mode toggle
    expect((await screen.findByRole('alert')).textContent).toBe('Invalid username or password')
  })

  it('stores only the session and reports the user on success', async () => {
    vi.spyOn(api, 'register').mockResolvedValue({ token: 't', user_id: 'u1', username: 'alice' })
    const onLogin = vi.fn()
    render(<Login onLogin={onLogin} />)
    await userEvent.click(screen.getByRole('button', { name: 'Create account', pressed: false }))
    expect(screen.getByRole('button', { name: 'Create account', pressed: true })).toBeTruthy()
    await userEvent.type(screen.getByLabelText('Username'), 'alice')
    await userEvent.type(screen.getByLabelText('Password'), 'long-enough-1')
    await userEvent.click(screen.getAllByRole('button', { name: 'Create account' }).at(-1)!)
    expect(onLogin).toHaveBeenCalledWith({ token: 't', user_id: 'u1', username: 'alice' })
    expect(session.current?.user_id).toBe('u1')
  })
})
