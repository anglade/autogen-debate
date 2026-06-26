import type { CSSProperties } from 'react'
import type { DebateMessage } from '../types'

interface Props {
  messages: DebateMessage[]
}

export function MessageFeed({ messages }: Props) {
  if (messages.length === 0) {
    return <p style={{ color: 'var(--muted)', textAlign: 'center', padding: '2rem 0' }}>Waiting for agents to speak…</p>
  }

  return (
    <div className="messages">
      {messages.map((msg) => (
        <article
          key={msg.id}
          className="message"
          style={{ '--msg-color': msg.color } as CSSProperties}
        >
          <header className="message-header">
            <span className="message-name">{msg.name}</span>
            <span className="message-role">{msg.role}</span>
          </header>
          <div className="message-body">{msg.content}</div>
        </article>
      ))}
    </div>
  )
}
