import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { POLL_DELAYS_MS } from '../hooks/useLearningStatus'
import { api, type AutoMemoryResult } from '../services/api'
import LearningPanel from './LearningPanel'

const pending: AutoMemoryResult = { status: 'pending', message: 'Learning from this analysis…', items: [], timings_ms: {} }
const stored: AutoMemoryResult = {
  status: 'stored',
  message: '1 knowledge item(s) stored in Hindsight as unconfirmed hypotheses.',
  items: [{ category: 'root_cause', content: 'Suspected root cause (unconfirmed): pool too small' }],
  timings_ms: { memory_extraction: 900 },
}
const prefs = { status: 'ok' as const, message: '1 long-term preference(s) applied.', applied: ["End every summary with 'OK'."], changes: [] }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('LearningPanel', () => {
  it('polls the background learning status until it settles', async () => {
    const learning = vi.spyOn(api, 'learning').mockResolvedValueOnce(pending).mockResolvedValueOnce(stored)
    const onSettled = vi.fn()
    render(<LearningPanel incidentId="INC-BBBB0002" memory={pending} preferences={prefs} onSettled={onSettled} />)
    expect(screen.getByText('Learning from this incident…')).toBeTruthy()

    await act(() => vi.advanceTimersByTimeAsync(POLL_DELAYS_MS[0]))
    await act(() => vi.advanceTimersByTimeAsync(POLL_DELAYS_MS[1]))

    expect(learning).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Retained as hypothesis')).toBeTruthy()
    expect(screen.getByText(/pool too small/)).toBeTruthy()
    expect(onSettled).toHaveBeenCalledOnce()

    await act(() => vi.advanceTimersByTimeAsync(60_000))
    expect(learning).toHaveBeenCalledTimes(2) // stopped polling
  })

  it('gives up after a bounded number of attempts', async () => {
    const learning = vi.spyOn(api, 'learning').mockResolvedValue(pending)
    render(<LearningPanel incidentId="INC-BBBB0002" memory={pending} preferences={prefs} />)
    await act(() => vi.advanceTimersByTimeAsync(120_000))
    expect(learning).toHaveBeenCalledTimes(POLL_DELAYS_MS.length)
  })

  it('does not poll when learning already finished, and shows applied preferences', () => {
    const learning = vi.spyOn(api, 'learning')
    render(<LearningPanel incidentId="INC-BBBB0002" memory={stored} preferences={prefs} />)
    expect(learning).not.toHaveBeenCalled()
    expect(screen.getByText("End every summary with 'OK'.")).toBeTruthy()
  })
})
