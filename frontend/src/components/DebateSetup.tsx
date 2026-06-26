import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Agent, DebateConfig, DebateMode, DebateStyle } from '../types'

interface Props {
  onStart: (sessionId: string) => void
}

export function DebateSetup({ onStart }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [question, setQuestion] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [turnOrder, setTurnOrder] = useState<string[]>([])
  const [style, setStyle] = useState<DebateStyle>('debate')
  const [mode, setMode] = useState<DebateMode>('sequential')
  const [humanGate, setHumanGate] = useState(true)
  const [rounds, setRounds] = useState(2)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    api.getAgents().then((list) => {
      setAgents(list)
      const defaults = new Set(list.filter((a) => a.id !== 'judge' && a.id !== 'moderator').map((a) => a.id))
      defaults.add('judge')
      setSelected(defaults)
      setTurnOrder(list.filter((a) => a.id !== 'judge' && a.id !== 'moderator').map((a) => a.id))
    }).catch((e) => setError(e.message))
  }, [])

  const toggleAgent = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  useEffect(() => {
    setTurnOrder((prev) => {
      const filtered = prev.filter((id) => selected.has(id) && id !== 'judge')
      const newcomers = [...selected].filter((id) => id !== 'judge' && !filtered.includes(id))
      return [...filtered, ...newcomers]
    })
  }, [selected])

  const orderedAgents = turnOrder
    .map((id) => agents.find((a) => a.id === id))
    .filter(Boolean) as Agent[]

  const onDragStart = (idx: number) => setDragIdx(idx)
  const onDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault()
    if (dragIdx === null || dragIdx === idx) return
    setTurnOrder((prev) => {
      const next = [...prev]
      const [item] = next.splice(dragIdx, 1)
      next.splice(idx, 0, item)
      return next
    })
    setDragIdx(idx)
  }

  const start = async () => {
    if (!question.trim()) { setError('Enter a question.'); return }
    const participant_ids = [...selected]
    if (participant_ids.length < 1) { setError('Select at least one agent.'); return }

    const config: DebateConfig = {
      question: question.trim(),
      participant_ids,
      turn_order: turnOrder.filter((id) => selected.has(id)),
      style,
      mode: style === 'debate' ? mode : 'dynamic',
      human_gate: humanGate,
      rounds,
      judge_id: 'judge',
    }

    setStarting(true)
    setError('')
    try {
      const { session_id } = await api.startDebate(config)
      onStart(session_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setStarting(false)
    }
  }

  const showTurnOrder = style === 'debate' && mode !== 'dynamic'

  return (
    <div>
      <h2 className="section-title">Debate Setup</h2>
      <p className="section-desc">Configure participants, style, and options before starting.</p>

      {error && <div className="error-banner">{error}</div>}

      <div className="card" style={{ marginBottom: '1rem' }}>
        <div className="field">
          <label>Question</label>
          <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What should the agents debate?" />
        </div>
      </div>

      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '0.95rem', marginBottom: '0.75rem' }}>Participants</h3>
        {agents.filter((a) => a.id !== 'moderator').map((agent) => (
          <label key={agent.id} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={selected.has(agent.id)}
              onChange={() => toggleAgent(agent.id)}
              style={{ accentColor: 'var(--primary)' }}
            />
            <span className="turn-dot" style={{ background: agent.color }} />
            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{agent.name}</span>
            <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>{agent.role}</span>
          </label>
        ))}
      </div>

      {showTurnOrder && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '0.95rem', marginBottom: '0.75rem' }}>Turn order <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(drag to reorder)</span></h3>
          <ul className="turn-list">
            {orderedAgents.map((agent, idx) => (
              <li
                key={agent.id}
                className={`turn-item${dragIdx === idx ? ' dragging' : ''}`}
                draggable
                onDragStart={() => onDragStart(idx)}
                onDragOver={(e) => onDragOver(e, idx)}
                onDragEnd={() => setDragIdx(null)}
              >
                <span className="turn-handle">⠿</span>
                <span className="turn-dot" style={{ background: agent.color }} />
                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{agent.name}</span>
                <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>{agent.role}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '0.95rem', marginBottom: '0.75rem' }}>Style</h3>
        <div className="style-toggle style-toggle-3">
          <button
            type="button"
            className={`style-toggle-btn${style === 'debate' ? ' selected' : ''}`}
            onClick={() => setStyle('debate')}
          >
            <span className="style-toggle-title">Debate</span>
            <span className="style-toggle-desc">Structured turns with configurable speaking order</span>
          </button>
          <button
            type="button"
            className={`style-toggle-btn${style === 'conversation' ? ' selected' : ''}`}
            onClick={() => setStyle('conversation')}
          >
            <span className="style-toggle-title">Conversation</span>
            <span className="style-toggle-desc">Free-flowing discussion — no moderator</span>
          </button>
          <button
            type="button"
            className={`style-toggle-btn${style === 'conversation_beta' ? ' selected' : ''}`}
            onClick={() => setStyle('conversation_beta')}
          >
            <span className="style-toggle-title">Conversation+ <span className="beta-tag">Beta</span></span>
            <span className="style-toggle-desc">Moderator RED/GREEN checks — re-anchor and consensus voting</span>
          </button>
        </div>
      </div>

      {style === 'debate' && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '0.95rem', marginBottom: '0.75rem' }}>Debate mode</h3>
          <div className="mode-options">
            {([
              ['sequential', 'Sequential', 'Agents speak in your preset order each round'],
              ['dynamic', 'Dynamic', 'GroupChatManager picks the next speaker by relevance'],
              ['manual', 'Manual', 'You choose who speaks next at every step'],
            ] as const).map(([value, title, desc]) => (
              <label key={value} className={`mode-option${mode === value ? ' selected' : ''}`}>
                <input type="radio" name="mode" value={value} checked={mode === value} onChange={() => setMode(value)} />
                <div>
                  <div className="mode-option-title">{title}</div>
                  <div className="mode-option-desc">{desc}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: '1rem' }}>
        <div className="toggle-row">
          <div>
            <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>Human gate between every turn</div>
            <div style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>Pause for your approval before the next agent speaks</div>
          </div>
          <label className="toggle">
            <input type="checkbox" checked={humanGate} onChange={(e) => setHumanGate(e.target.checked)} />
            <span className="toggle-slider" />
          </label>
        </div>
        <div className="field" style={{ marginTop: '0.75rem', marginBottom: 0 }}>
          {style === 'debate' && (
            <>
              <label>Debate rounds</label>
              <input type="number" min={1} max={10} value={rounds} onChange={(e) => setRounds(parseInt(e.target.value) || 1)} />
            </>
          )}
        </div>
      </div>

      <button className="btn-primary" onClick={start} disabled={starting}>
        {starting
          ? 'Starting…'
          : style === 'conversation'
            ? 'Start Conversation'
            : style === 'conversation_beta'
              ? 'Start Conversation+'
              : 'Start Debate'}
      </button>
    </div>
  )
}
