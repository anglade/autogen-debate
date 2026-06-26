export interface Agent {
  id: string
  name: string
  role: string
  system_message: string
  temperature: number
  color: string
  builtin?: boolean
  is_system_agent?: boolean
  beta_only?: boolean
  selectable?: boolean
}

export type DebateMode = 'sequential' | 'dynamic' | 'manual'

export type DebateStyle = 'debate' | 'conversation' | 'conversation_beta'

export interface DebateConfig {
  question: string
  participant_ids: string[]
  turn_order: string[]
  style: DebateStyle
  mode: DebateMode
  human_gate: boolean
  rounds: number
  judge_id: string
}

export interface DebateMessage {
  id: string
  name: string
  agent_id: string
  role: string
  color: string
  content: string
}

export interface SpeakerOption {
  id: string
  name: string
  role: string
  color: string
}

export interface DebateStatus {
  session_id: string
  question: string
  messages: DebateMessage[]
  status: 'starting' | 'running' | 'waiting_human' | 'waiting_manual_pick' | 'complete' | 'error'
  error?: string
  human_prompt?: string
  style: DebateStyle
  mode: DebateMode
  human_gate: boolean
  available_speakers: SpeakerOption[]
  participant_ids: string[]
  conversation_agent_messages: number
  show_verdict_prompt: boolean
  show_escalation_prompt: boolean
}
