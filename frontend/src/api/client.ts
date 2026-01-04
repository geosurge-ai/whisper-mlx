/**
 * Typed API Client for Qwen Daemon
 *
 * Features:
 * - Full type safety for all endpoints
 * - Automatic error handling
 * - Offline detection
 * - Request/response logging in dev
 */

import type {
  HealthResponse,
  ProfileInfo,
  ToolInfo,
  ChatRequest,
  ChatResponse,
  ToolInvokeRequest,
  ToolInvokeResponse,
  Session,
  SessionSummary,
  CreateSessionRequest,
  SessionChatRequest,
  SessionChatResponse,
  GenerationStatus,
  GenerationEvent,
} from './types'

// Base URL - proxied through Vite in dev, direct in prod
const API_BASE = '/api'

// --- Error Types ---

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export class NetworkError extends Error {
  constructor(message: string = 'Network request failed') {
    super(message)
    this.name = 'NetworkError'
  }
}

// --- Fetch Wrapper ---

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  try {
    const response = await fetch(url, { ...options, headers })

    if (!response.ok) {
      let detail: string | undefined
      try {
        const errorBody = await response.json() as { detail?: string }
        detail = errorBody.detail
      } catch {
        // Response body not JSON
      }
      throw new ApiError(
        `API request failed: ${response.status} ${response.statusText}`,
        response.status,
        detail
      )
    }

    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }
    // Network error (offline, CORS, etc.)
    throw new NetworkError(
      error instanceof Error ? error.message : 'Network request failed'
    )
  }
}

// --- API Methods ---

/**
 * Check daemon health and get status info
 */
export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health')
}

/**
 * List all available agent profiles
 */
export async function getProfiles(): Promise<ProfileInfo[]> {
  return apiFetch<ProfileInfo[]>('/v1/profiles')
}

/**
 * List all available tools
 */
export async function getTools(): Promise<ToolInfo[]> {
  return apiFetch<ToolInfo[]>('/v1/tools')
}

/**
 * Get tools for a specific profile
 */
export async function getProfileTools(profileName: string): Promise<ToolInfo[]> {
  return apiFetch<ToolInfo[]>(`/v1/profiles/${encodeURIComponent(profileName)}/tools`)
}

/**
 * Send a chat message and get response
 */
export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/v1/chat', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

/**
 * Invoke a tool directly
 */
export async function invokeTool(request: ToolInvokeRequest): Promise<ToolInvokeResponse> {
  return apiFetch<ToolInvokeResponse>('/v1/invoke-tool', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

// --- Generation Status ---

/**
 * Get current generation queue status
 *
 * Returns which session is currently generating and which are queued.
 */
export async function getGenerationStatus(): Promise<GenerationStatus> {
  return apiFetch<GenerationStatus>('/v1/generation/status')
}

// --- Session API ---

/**
 * List all sessions (summaries only, sorted by most recent)
 */
export async function listSessions(limit: number = 50): Promise<SessionSummary[]> {
  return apiFetch<SessionSummary[]>(`/v1/sessions?limit=${limit}`)
}

/**
 * Create a new session
 */
export async function createSession(request: CreateSessionRequest = {}): Promise<Session> {
  return apiFetch<Session>('/v1/sessions', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

/**
 * Get a session by ID (includes full message history)
 */
export async function getSession(sessionId: string): Promise<Session> {
  return apiFetch<Session>(`/v1/sessions/${encodeURIComponent(sessionId)}`)
}

/**
 * Delete a session
 */
export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch<{ deleted: boolean }>(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

/**
 * Send a message in a session
 *
 * This uses the generation semaphore on the backend -
 * only one generation can happen at a time.
 */
export async function sendSessionChat(
  sessionId: string,
  request: SessionChatRequest
): Promise<SessionChatResponse> {
  return apiFetch<SessionChatResponse>(`/v1/sessions/${encodeURIComponent(sessionId)}/chat`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

/**
 * Send a message in a session with SSE streaming for real-time progress.
 *
 * Events are streamed as they occur:
 * - round_start: New inference round started
 * - generating: Model is thinking
 * - tool_start: Tool execution started
 * - tool_end: Tool execution finished
 * - complete: Generation finished (includes full session)
 * - error: An error occurred
 *
 * @param sessionId - Session ID to send message to
 * @param request - Chat request (message, model_size, etc.)
 * @param onEvent - Callback for each SSE event
 * @returns Promise that resolves when stream completes
 */
export async function streamSessionChat(
  sessionId: string,
  request: SessionChatRequest,
  onEvent: (event: GenerationEvent) => void
): Promise<void> {
  const url = `${API_BASE}/v1/sessions/${encodeURIComponent(sessionId)}/chat/stream`

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    let detail: string | undefined
    try {
      const errorBody = (await response.json()) as { detail?: string }
      detail = errorBody.detail
    } catch {
      // Response body not JSON
    }
    throw new ApiError(
      `API request failed: ${response.status} ${response.statusText}`,
      response.status,
      detail
    )
  }

  if (!response.body) {
    throw new NetworkError('Response body is null')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()

      if (done) {
        break
      }

      buffer += decoder.decode(value, { stream: true })

      // Parse SSE events from buffer
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6) // Remove 'data: ' prefix
          if (data.trim()) {
            try {
              const event = JSON.parse(data) as GenerationEvent
              onEvent(event)
            } catch (e) {
              console.warn('Failed to parse SSE event:', data, e)
            }
          }
        }
      }
    }

    // Process any remaining data in buffer
    if (buffer.startsWith('data: ')) {
      const data = buffer.slice(6)
      if (data.trim()) {
        try {
          const event = JSON.parse(data) as GenerationEvent
          onEvent(event)
        } catch (e) {
          console.warn('Failed to parse final SSE event:', data, e)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// --- Connection Status ---

export type ConnectionStatus = 'online' | 'offline' | 'checking'

/**
 * Check if daemon is reachable
 */
export async function checkConnection(): Promise<boolean> {
  try {
    await getHealth()
    return true
  } catch {
    return false
  }
}
