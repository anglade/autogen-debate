import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Agent } from '../types'
import { AgentCard } from './AgentCard'
import { AgentForm } from './AgentForm'

export function AgentLibrary() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Agent | null>(null)
  const [creating, setCreating] = useState(false)

  const load = async () => {
    try {
      setAgents(await api.getAgents())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load agents')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleSave = async (payload: Partial<Agent>) => {
    if (editing) {
      await api.updateAgent(editing.id, payload)
      setEditing(null)
    } else {
      await api.createAgent(payload)
      setCreating(false)
    }
    await load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this agent?')) return
    try {
      await api.deleteAgent(id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  const handleEdit = (agent: Agent) => {
    if (agent.is_system_agent || agent.id === 'moderator') return
    setEditing(agent)
    setCreating(false)
  }

  if (loading) return <p style={{ color: 'var(--muted)' }}>Loading agents…</p>

  return (
    <div>
      <h2 className="section-title">Agent Library</h2>
      <p className="section-desc">
        Preloaded debate agents are editable. Create custom agents for specialized roles.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="actions-row" style={{ marginBottom: '1.25rem' }}>
        <button className="btn-primary" onClick={() => { setCreating(true); setEditing(null) }}>
          + Create New Agent
        </button>
      </div>

      {(creating || editing) && (
        <div style={{ marginBottom: '1.25rem' }}>
          <AgentForm
            agent={editing ?? undefined}
            onSave={handleSave}
            onCancel={() => { setCreating(false); setEditing(null) }}
          />
        </div>
      )}

      <div className="grid-2">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            onEdit={() => handleEdit(agent)}
            onDelete={() => handleDelete(agent.id)}
          />
        ))}
      </div>
    </div>
  )
}
