import type { AnalyzeResponse, RecalledIncident, RecallResult } from '../services/api'

export const recalled = (overrides: Partial<RecalledIncident> = {}): RecalledIncident => ({
  incident_id: 'INC-AAAA0001',
  title: 'Payment API Latency',
  service: 'payment-api',
  environment: 'production',
  severity: 'High',
  root_cause: 'Redis connection pool exhaustion',
  solution: 'Increased pool from 50 to 150',
  outcome: 'Latency back to normal',
  failed_approaches: 'Restarting pods',
  error_signature: 'connection pool exhausted',
  recent_changes: null,
  resolved_at: '2026-09-01T10:00:00+00:00',
  relevance_score: 0.82,
  confirmed: true,
  why_relevant: ['Same service: payment-api', 'Hindsight semantic relevance: 0.82'],
  facts: [{ text: 'payment-api pool exhausted at 50', type: 'world', score: 0.8 }],
  ...overrides,
})

export const recall = (overrides: Partial<RecallResult> = {}): RecallResult => ({
  status: 'ok',
  message: '1 relevant previous incident recalled from Hindsight',
  query: 'q',
  memories: [recalled()],
  other_facts: [],
  ...overrides,
})

export const analyzeResponse = (overrides: Partial<AnalyzeResponse> = {}): AnalyzeResponse => ({
  incident_id: 'INC-BBBB0002',
  model: 'openai/gpt-oss-120b',
  recall: recall(),
  analysis: {
    summary: 'Redis pressure again.',
    possible_causes: [{ cause: 'Pool too small', likelihood: 'High', evidence: 'timeouts' }],
    historical_matches: [],
    recommended_checks: ['Check pool'],
    recommended_solution: 'Resize pool',
    confidence: 'High',
    confidence_reason: 'Matches history',
  },
  memory: { status: 'pending', message: 'Learning…', items: [], timings_ms: {} },
  preferences: { status: 'ok', message: 'No long-term preferences stored yet.', applied: [], changes: [] },
  metrics: {
    total_ms: 1834,
    stages_ms: { hindsight_recall: 320, preferences_load: 180, groq_analysis: 1210, db_write: 4 },
    memories_recalled: 1,
    facts_in_prompt: 1,
    prompt_chars: 2400,
    prompt_tokens: 610,
    completion_tokens: 240,
  },
  ...overrides,
})
