import { useState } from 'react'
import { api } from '../api'

interface Props {
  sessionId: string
  onContinue: () => void
}

export function HumanGatePanel({ sessionId, onContinue }: Props) {
  const [feedback, setFeedback] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    setLoading(true)
    try {
      await api.continueDebate(sessionId, feedback)
      setFeedback('')
      onContinue()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card human-panel">
      <h3 style={{ fontSize: '0.95rem', marginBottom: '0.35rem' }}>Your turn</h3>
      <p style={{ color: 'var(--muted)', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
        Approve the last response or add feedback to steer the agents.
      </p>
      <div className="field">
        <label>Feedback <span style={{ fontWeight: 400 }}>(optional)</span></label>
        <textarea
          rows={3}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Leave empty to continue without changes…"
        />
      </div>
      <button className="btn-primary" onClick={submit} disabled={loading}>
        {loading ? 'Continuing…' : 'Continue'}
      </button>
    </div>
  )
}
