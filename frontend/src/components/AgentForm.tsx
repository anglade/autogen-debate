import { useState } from 'react'
import type { Agent } from '../types'

interface Props {
  agent?: Agent
  onSave: (payload: Partial<Agent>) => Promise<void>
  onCancel: () => void
}

export function AgentForm({ agent, onSave, onCancel }: Props) {
  const [name, setName] = useState(agent?.name ?? '')
  const [role, setRole] = useState(agent?.role ?? '')
  const [systemMessage, setSystemMessage] = useState(agent?.system_message ?? '')
  const [temperature, setTemperature] = useState(agent?.temperature ?? 0.7)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!name.trim() || !systemMessage.trim()) {
      setError('Name and system message are required.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave({ name, role, system_message: systemMessage, temperature })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <h3 style={{ marginBottom: '1rem' }}>{agent ? 'Edit Agent' : 'Create New Agent'}</h3>
      {error && <div className="error-banner">{error}</div>}
      <div className="field">
        <label>Name</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Strategist" />
      </div>
      <div className="field">
        <label>Role description</label>
        <input type="text" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Short role shown in the UI" />
      </div>
      <div className="field">
        <label>System message</label>
        <textarea rows={5} value={systemMessage} onChange={(e) => setSystemMessage(e.target.value)} placeholder="Instructions for this agent…" />
      </div>
      <div className="field">
        <label>Temperature ({temperature})</label>
        <input type="range" min={0} max={1} step={0.1} value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} />
      </div>
      <div className="actions-row">
        <button className="btn-primary" onClick={submit} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}
