/**
 * API Types - matches daemon/server.py Pydantic models
 */

// --- Health ---

export interface HealthResponse {
  status: string
  model_loaded: boolean
  model_size: string | null
  generation_in_progress: boolean
  available_profiles: string[]
  available_tools: string[]
}

// --- Profiles ---

export interface ProfileInfo {
  name: string
  system_prompt_preview: string
  tool_names: string[]
  max_tool_rounds: number
}

// --- Tools ---

export interface ToolInfo {
  name: string
  description: string
  parameters: Record<string, unknown>
}

// --- Chat ---

export interface ChatMessageInput {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  message: string
  profile?: string
  model_size?: 'small' | 'medium' | 'large'
  history?: ChatMessageInput[]
  verbose?: boolean
}

export interface ToolCallInfo {
  name: string
  arguments: Record<string, unknown>
}

export interface ToolResultInfo {
  tool_name: string
  result: unknown
}

export interface ChatResponse {
  content: string
  tool_calls: ToolCallInfo[]
  tool_results: ToolResultInfo[]
  rounds_used: number
  finished: boolean
  latency_ms: number
}

// --- Tool Invocation ---

export interface ToolInvokeRequest {
  tool_name: string
  arguments: Record<string, unknown>
}

export interface ToolInvokeResponse {
  tool_name: string
  result: unknown
  latency_ms: number
}

// --- Sessions ---

export interface SessionMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  tool_calls: ToolCallInfo[]
  tool_results: ToolResultInfo[]
}

export interface Session {
  id: string
  profile_name: string
  created_at: number
  updated_at: number
  messages: SessionMessage[]
  title: string | null
}

export interface SessionSummary {
  id: string
  profile_name: string
  title: string | null
  created_at: number
  updated_at: number
  message_count: number
}

export interface CreateSessionRequest {
  profile_name?: string
}

export interface SessionChatRequest {
  message: string
  model_size?: 'small' | 'medium' | 'large'
  verbose?: boolean
}

export interface QueueStats {
  was_queued: boolean
  queue_wait_ms: number
  queue_position: number
}

export interface SessionChatResponse {
  session: Session
  response: ChatResponse
  queue_stats: QueueStats
}

// --- Generation Status ---

export interface GenerationStatus {
  generating_session_id: string | null
  queued_session_ids: string[]
}

// --- SSE Generation Events ---

export type GenerationEventType =
  | 'round_start'
  | 'generating'
  | 'thinking'
  | 'tool_start'
  | 'tool_end'
  | 'complete'
  | 'error'

export interface GenerationEvent {
  type: GenerationEventType
  round?: number
  max_rounds?: number
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_result?: string
  content?: string  // For 'thinking' events
  session?: Session
  response?: ChatResponse
  queue_stats?: QueueStats
  error?: string
  timestamp: number
}

// --- API Error Response ---

export interface ApiErrorResponse {
  detail: string
}
