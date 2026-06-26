import { useState } from 'react'
import { api } from '../api'
import type { SpeakerOption } from '../types'

interface Props {
  sessionId: string
  speakers: SpeakerOption[]
  onPick: () => void
}

export function ManualPickPanel({ sessionId, speakers, onPick }: Props) {
  const [loading, setLoading] = useState<string | null>(null)

  const pick = async (agentId: string) => {
    setLoading(agentId)
    try {
      await api.pickSpeaker(sessionId, agentId)
      onPick()
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="card manual-panel">
      <h3 style={{ fontSize: '0.95rem', marginBottom: '0.35rem' }}>Choose next speaker</h3>
      <p style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>Select which agent should speak next.</p>
      <div className="speaker-grid">
        {speakers.map((s) => (
          <button
            key={s.id}
            className="speaker-btn"
            onClick={() => pick(s.id)}
            disabled={loading !== null}
          >
            <span className="turn-dot" style={{ background: s.color }} />
            <span>{s.name}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
