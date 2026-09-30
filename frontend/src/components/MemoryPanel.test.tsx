import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { recall, recalled } from '../test/fixtures'
import MemoryPanel from './MemoryPanel'

describe('MemoryPanel', () => {
  it('labels confirmed knowledge and hypotheses in text, not only colour', () => {
    render(
      <MemoryPanel
        recall={recall({
          memories: [
            recalled(),
            recalled({ incident_id: 'INC-AAAA0003', confirmed: false, root_cause: 'Suspected (unconfirmed): DNS', resolved_at: null }),
          ],
        })}
      />,
    )
    const [confirmed, hypothesis] = screen.getAllByRole('article')
    expect(within(confirmed).getByText(/Confirmed resolution/)).toBeTruthy()
    expect(within(confirmed).getByText('Confirmed root cause')).toBeTruthy()
    expect(within(hypothesis).getByText(/Unconfirmed hypothesis/)).toBeTruthy()
    expect(within(hypothesis).getByText('Suspected root cause')).toBeTruthy()
  })

  it('explains why a memory was recalled and that memory is evidence, not the answer', () => {
    render(<MemoryPanel recall={recall()} />)
    expect(screen.getByText('Historical memory is evidence, not the answer.')).toBeTruthy()
    expect(screen.getByText('Same service: payment-api')).toBeTruthy()
  })

  it('announces unavailable memory as an alert', () => {
    render(<MemoryPanel recall={recall({ status: 'error', memories: [], message: 'Historical memory was unavailable' })} />)
    expect(screen.getByRole('alert').textContent).toContain('Historical memory was unavailable')
    expect(screen.queryByRole('article')).toBeNull()
  })

  it('does not show the evidence note or any incident when there is no memory yet', () => {
    render(<MemoryPanel recall={recall({ status: 'empty', memories: [], message: 'no relevant previous incidents' })} />)
    expect(screen.queryByText(/evidence, not the answer/)).toBeNull()
    expect(screen.getByText(/the agent will remember it/)).toBeTruthy()
  })
})
