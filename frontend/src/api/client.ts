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
