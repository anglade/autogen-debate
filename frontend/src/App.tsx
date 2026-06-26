import { useState } from 'react'
import { AgentLibrary } from './components/AgentLibrary'
import { DebateSetup } from './components/DebateSetup'
import { DebateScreen } from './components/DebateScreen'

type Tab = 'library' | 'setup' | 'debate'

export default function App() {
  const [tab, setTab] = useState<Tab>('library')
  const [sessionId, setSessionId] = useState<string | null>(null)

  const startDebate = (id: string) => {
    setSessionId(id)
    setTab('debate')
  }

  const newDebate = () => {
    setSessionId(null)
    setTab('setup')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agent Debate</h1>
        <nav className="nav-tabs">
          <button className={`nav-tab${tab === 'library' ? ' active' : ''}`} onClick={() => setTab('library')}>
            Agent Library
          </button>
          <button className={`nav-tab${tab === 'setup' ? ' active' : ''}`} onClick={() => setTab('setup')}>
            Debate Setup
          </button>
          <button
            className={`nav-tab${tab === 'debate' ? ' active' : ''}`}
            onClick={() => sessionId && setTab('debate')}
            disabled={!sessionId}
          >
            Debate
          </button>
        </nav>
      </header>

      {tab === 'library' && <AgentLibrary />}
      {tab === 'setup' && <DebateSetup onStart={startDebate} />}
      {tab === 'debate' && sessionId && (
        <DebateScreen sessionId={sessionId} onNewDebate={newDebate} />
      )}
    </div>
  )
}
