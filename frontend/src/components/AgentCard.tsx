import type { CSSProperties } from 'react'
import type { Agent } from '../types'

interface Props {
  agent: Agent
  onEdit: () => void
  onDelete: () => void
}

export function AgentCard({ agent, onEdit, onDelete }: Props) {
  const isSystemAgent = agent.is_system_agent || agent.id === 'moderator'

  return (
    <div className={`card agent-card${isSystemAgent ? ' agent-card-system' : ''}`} style={{ '--agent-color': agent.color } as CSSProperties}>
      <div className="agent-card-header">
        <div>
          <div className="agent-card-name">{agent.name}</div>
          <div className="agent-card-badges">
            {isSystemAgent && <span className="badge badge-system">System agent</span>}
            {agent.beta_only && <span className="badge badge-beta">Beta only</span>}
            {agent.builtin && !isSystemAgent && <span className="badge badge-builtin">Built-in</span>}
          </div>
        </div>
        {!isSystemAgent && (
          <div className="actions-row" style={{ margin: 0 }}>
            <button className="btn-ghost" style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem' }} onClick={onEdit}>
              Edit
            </button>
            {!agent.builtin && (
              <button className="btn-danger" style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem' }} onClick={onDelete}>
                Delete
              </button>
            )}
          </div>
        )}
      </div>
      <div className="agent-card-role">
        {isSystemAgent
          ? 'Detects drift and checks for consensus. Active in Conversation+ [Beta] only.'
          : agent.role}
      </div>
      {isSystemAgent ? (
        <div className="agent-card-meta agent-card-status">Non-editable · System agent</div>
      ) : (
        <div className="agent-card-meta">Temperature: {agent.temperature}</div>
      )}
    </div>
  )
}
