import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { analyzeResponse, recall, recalled } from '../test/fixtures'
import AnalysisPanel from './AnalysisPanel'

const headings = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)

describe('AnalysisPanel', () => {
  it('presents the analysis in reasoning order: current incident, historical evidence, comparison, reasoning, recommendation', () => {
    const result = analyzeResponse()
    result.analysis.historical_matches = [
      { incident: 'INC-AAAA0001', similarities: ['Redis timeouts on payment-api'], differences: ['Traffic is 40% higher'], how_it_applies: 'Pool may be too small again' },
    ]
    render(<AnalysisPanel result={result} />)
    expect(headings()).toEqual([
      'Current incident',
      'Historical evidence',
      'Similarities and differences with historical incidents',
      'Reasoning — possible causes',
      'Recommended checks',
      'Recommended solution',
      'Confidence',
    ])
    expect(screen.getByText('Redis timeouts on payment-api')).toBeTruthy()
    expect(screen.getByText('Traffic is 40% higher')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Show exact prompt sent to Groq/ })).toBeTruthy()
  })

  it('states how much historical evidence was used, split by trust', () => {
    const memories = [recalled(), recalled({ incident_id: 'INC-AAAA0003', confirmed: false })]
    render(<AnalysisPanel result={analyzeResponse({ recall: recall({ memories }) })} />)
    expect(screen.getByText(/2 historical incidents from Hindsight were given to Groq as evidence \(1 confirmed resolution, 1 unconfirmed hypothesis\)/)).toBeTruthy()
  })

  it('says plainly when the analysis ran without historical memory', () => {
    render(<AnalysisPanel result={analyzeResponse({ recall: recall({ status: 'error', memories: [], message: 'down' }) })} />)
    expect(screen.getByText(/analyzed without historical memory/)).toBeTruthy()
    expect(screen.getByText('No historical incidents were compared for this analysis.')).toBeTruthy()
  })
})
