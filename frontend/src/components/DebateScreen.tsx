import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { DebateStatus } from '../types'
import { HumanGatePanel } from './HumanGatePanel'
import { ManualPickPanel } from './ManualPickPanel'
import { MessageFeed } from './MessageFeed'

interface Props {
  sessionId: string
  onNewDebate: () => void
}

const STATUS_LABELS: Record<string, string> = {
  starting: 'Starting debate…',
  running: 'Agents are debating…',
  waiting_human: 'Waiting for your input',
  waiting_manual_pick: 'Choose the next speaker',
  complete: 'Debate complete',
  error: 'Error',
}

export function DebateScreen({ sessionId, onNewDebate }: Props) {
  const [status, setStatus] = useState<DebateStatus | null>(null)
  const [ending, setEnding] = useState(false)
  const [dismissing, setDismissing] = useState(false)
  const [dismissingEscalation, setDismissingEscalation] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const poll = useCallback(async () => {
    try {
      const data = await api.getDebateStatus(sessionId)
      setStatus(data)
      if (data.status === 'complete' || data.status === 'error') {
        if (pollRef.current) clearInterval(pollRef.current)
      }
    } catch {
      /* keep polling */
    }
  }, [sessionId])

  useEffect(() => {
    poll()
    pollRef.current = setInterval(poll, 800)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [poll])

  const endDebate = async () => {
    setEnding(true)
    try {
      await api.endDebate(sessionId)
      poll()
    } finally {
      setEnding(false)
    }
  }

  const keepGoing = async () => {
    setDismissing(true)
    try {
      await api.dismissVerdictPrompt(sessionId)
      poll()
    } finally {
      setDismissing(false)
    }
  }

  const keepGoingAfterEscalation = async () => {
    setDismissingEscalation(true)
    try {
      await api.dismissEscalationPrompt(sessionId)
      poll()
    } finally {
      setDismissingEscalation(false)
    }
  }

  const isConversation = status?.style === 'conversation' || status?.style === 'conversation_beta'
  const isConversationBeta = status?.style === 'conversation_beta'

  const screenTitle = isConversationBeta
    ? 'Conversation+ [Beta]'
    : isConversation
      ? 'Conversation'
      : 'Debate'

  if (!status) {
    return <p style={{ color: 'var(--muted)' }}>Loading debate…</p>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <div>
          <h2 className="section-title">{screenTitle}</h2>
          <div className="status-pill">
            {status.status !== 'complete' && status.status !== 'error' && <span className="status-dot" />}
            {isConversation && status.status === 'running' ? 'Agents are talking…' : (STATUS_LABELS[status.status] ?? status.status)}
          </div>
        </div>
        <div className="actions-row" style={{ margin: 0 }}>
          {status.status !== 'complete' && status.status !== 'error' && (
            <button className="btn-danger" onClick={endDebate} disabled={ending}>
              {ending ? 'Ending…' : 'End debate → Judge verdict'}
            </button>
          )}
          {(status.status === 'complete' || status.status === 'error') && (
            <button className="btn-secondary" onClick={onNewDebate}>New debate</button>
          )}
        </div>
      </div>

      {status.error && <div className="error-banner">{status.error}</div>}

      <div className="card debate-question">
        <label>Question</label>
        <p>{status.question}</p>
      </div>

      <MessageFeed messages={status.messages} />

      {status.show_escalation_prompt && (
        <div className="verdict-prompt escalation-prompt">
          <p>
            Consensus checks keep coming back mixed. The disagreement may be structural.
            Continue refining, or proceed to the Judge with the analysis so far?
          </p>
          <div className="verdict-prompt-actions">
            <button className="btn-primary" onClick={endDebate} disabled={ending}>
              {ending ? 'Ending…' : 'End & Get Verdict'}
            </button>
            <button className="btn-secondary" onClick={keepGoingAfterEscalation} disabled={dismissingEscalation}>
              {dismissingEscalation ? '…' : 'Keep Going'}
            </button>
          </div>
        </div>
      )}

      {status.show_verdict_prompt && (
        <div className="verdict-prompt">
          <p>The conversation has been going for a while. Ready for the Judge&apos;s verdict?</p>
          <div className="verdict-prompt-actions">
            <button className="btn-primary" onClick={endDebate} disabled={ending}>
              {ending ? 'Ending…' : 'End & Get Verdict'}
            </button>
            <button className="btn-secondary" onClick={keepGoing} disabled={dismissing}>
              {dismissing ? '…' : 'Keep Going'}
            </button>
          </div>
        </div>
      )}

      {status.status === 'waiting_human' && (
        <HumanGatePanel sessionId={sessionId} onContinue={poll} />
      )}

      {status.status === 'waiting_manual_pick' && (
        <ManualPickPanel sessionId={sessionId} speakers={status.available_speakers} onPick={poll} />
      )}
    </div>
  )
}
