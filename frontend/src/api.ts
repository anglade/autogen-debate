import type { Agent, DebateConfig, DebateStatus } from './types'

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Request failed')
  return data
}

export const api = {
  getAgents: () => request<Agent[]>('/agents'),
  createAgent: (payload: Partial<Agent>) =>
    request<Agent>('/agents', { method: 'POST', body: JSON.stringify(payload) }),
  updateAgent: (id: string, payload: Partial<Agent>) =>
    request<Agent>(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteAgent: (id: string) =>
    request<{ ok: boolean }>(`/agents/${id}`, { method: 'DELETE' }),
  startDebate: (config: DebateConfig) =>
    request<{ session_id: string }>('/debate/start', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  getDebateStatus: (sessionId: string) =>
    request<DebateStatus>(`/debate/${sessionId}/status`),
  continueDebate: (sessionId: string, feedback: string) =>
    request<{ ok: boolean }>(`/debate/${sessionId}/continue`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  pickSpeaker: (sessionId: string, agentId: string) =>
    request<{ ok: boolean }>(`/debate/${sessionId}/pick-speaker`, {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId }),
    }),
  endDebate: (sessionId: string) =>
    request<{ ok: boolean }>(`/debate/${sessionId}/end`, { method: 'POST' }),
  dismissVerdictPrompt: (sessionId: string) =>
    request<{ ok: boolean }>(`/debate/${sessionId}/dismiss-verdict-prompt`, { method: 'POST' }),
  dismissEscalationPrompt: (sessionId: string) =>
    request<{ ok: boolean }>(`/debate/${sessionId}/dismiss-escalation-prompt`, { method: 'POST' }),
}
