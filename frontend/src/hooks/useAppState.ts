/**
 * useAppState - Main application state hook
 *
 * Combines all state management with backend session persistence.
 * Sessions are stored on the backend, localStorage serves as cache.
 */

import { useState, useEffect, useCallback, useMemo, useRef, startTransition } from 'react'
import { useLocalStorage } from './useLocalStorage'
import type { ProfileInfo, ToolInfo, Session, SessionSummary, SessionMessage } from '../api'
import {
  getHealth,
  getProfiles,
  getProfileTools,
  listSessions,
  createSession as apiCreateSession,
  getSession as apiGetSession,
  sendSessionChat,
  getGenerationStatus,
  ApiError,
  NetworkError,
} from '../api'
import type { ChatMessage, Command } from '../components'

// --- Types ---

export interface AppState {
  // Connection
  connectionStatus: 'online' | 'offline' | 'checking'
  generationInProgress: boolean

  // Profiles
  profiles: ProfileInfo[]
  selectedProfile: string
  profileTools: ToolInfo[]

  // Sessions
  sessions: SessionSummary[]
  currentSession: Session | null
  chatLoading: boolean
  chatError: string | null

  // Command Palette
  paletteOpen: boolean
  recentCommands: string[]

  // Loading states
  profilesLoading: boolean
  toolsLoading: boolean
  sessionsLoading: boolean
}

// Re-export Session type for use in components
export type { Session }

// --- Hook ---

export function useAppState() {
  // Persisted state (cache/preferences)
  const [selectedProfile, setSelectedProfile] = useLocalStorage('qwen-profile', 'general')
  const [recentCommands, setRecentCommands] = useLocalStorage<string[]>('qwen-recent-commands', [])
  const [currentSessionId, setCurrentSessionId] = useLocalStorage<string | null>('qwen-current-session', null)

  // Ephemeral state
  const [connectionStatus, setConnectionStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [generationInProgress, setGenerationInProgress] = useState(false)
  const [generatingSessionId, setGeneratingSessionId] = useState<string | null>(null)
  const [queuedSessionIds, setQueuedSessionIds] = useState<string[]>([])
  const [profiles, setProfiles] = useState<ProfileInfo[]>([])
  const [profileTools, setProfileTools] = useState<ToolInfo[]>([])
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [profilesLoading, setProfilesLoading] = useState(true)
  const [toolsLoading, setToolsLoading] = useState(false)
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [chatLoading, setChatLoading] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)

  // Track previous generation state to detect when generation completes
  const prevGenerationInProgress = useRef(false)

  // --- Debug Logging Helper ---
  const debug = (msg: string, data?: unknown) => {
    if (data !== undefined) {
      console.log(`[useAppState] ${msg}`, data)
    } else {
      console.log(`[useAppState] ${msg}`)
    }
  }

  // --- Effects ---

  // Check connection on mount
  useEffect(() => {
    let isInitialCheck = true

    async function checkConnection() {
      // Only show 'checking' on initial load, not on periodic checks
      // This prevents re-triggering effects that depend on connectionStatus
      if (isInitialCheck) {
        setConnectionStatus('checking')
        isInitialCheck = false
      }
      try {
        const health = await getHealth()
        debug(`Health check: model_loaded=${health.model_loaded}, generating=${health.generation_in_progress}`)
        setConnectionStatus('online')
        setGenerationInProgress(health.generation_in_progress)
      } catch (err) {
        debug('Health check failed, going offline', err)
        setConnectionStatus('offline')
      }
    }

    void checkConnection()

    // Recheck connection every 10s
    const interval = setInterval(() => void checkConnection(), 10000)
    return () => clearInterval(interval)
  }, [])

  // Poll generation status more frequently when generation is in progress
  useEffect(() => {
    if (connectionStatus !== 'online') return
    if (!generationInProgress && !chatLoading) return

    debug(`Starting generation polling (generationInProgress=${generationInProgress}, chatLoading=${chatLoading})`)

    async function pollGenerationStatus() {
      try {
        const status = await getGenerationStatus()
        if (status.generating_session_id || status.queued_session_ids.length > 0) {
          debug(`Poll: generating=${status.generating_session_id?.slice(0, 8)}, queued=${status.queued_session_ids.length}`)
        }
        setGeneratingSessionId(status.generating_session_id)
        setQueuedSessionIds(status.queued_session_ids)
        // Update generationInProgress based on actual backend state
        const isActive = status.generating_session_id !== null || status.queued_session_ids.length > 0
        if (isActive !== generationInProgress) {
          debug(`Generation state changed: ${generationInProgress} -> ${isActive}`)
        }
        setGenerationInProgress(isActive)
      } catch (err) {
        debug('Poll failed', err)
      }
    }

    void pollGenerationStatus()

    // Poll every 2 seconds during generation
    const interval = setInterval(() => void pollGenerationStatus(), 2000)
    return () => clearInterval(interval)
  }, [connectionStatus, generationInProgress, chatLoading])

  // Fetch profiles when online
  useEffect(() => {
    if (connectionStatus !== 'online') return

    async function fetchProfiles() {
      setProfilesLoading(true)
      try {
        const data = await getProfiles()
        setProfiles(data)
      } catch (error) {
        console.error('Failed to fetch profiles:', error)
      } finally {
        setProfilesLoading(false)
      }
    }

    void fetchProfiles()
  }, [connectionStatus])

  // Fetch tools when profile changes
  useEffect(() => {
    if (connectionStatus !== 'online' || !selectedProfile) return

    async function fetchTools() {
      setToolsLoading(true)
      try {
        const data = await getProfileTools(selectedProfile)
        setProfileTools(data)
      } catch {
        setProfileTools([])
      } finally {
        setToolsLoading(false)
      }
    }

    void fetchTools()
  }, [connectionStatus, selectedProfile])

  // Fetch sessions from backend when online (initial load only)
  useEffect(() => {
    if (connectionStatus !== 'online') return

    async function fetchSessions() {
      debug('Fetching sessions from backend (initial)...')
      setSessionsLoading(true)
      try {
        const data = await listSessions()
        debug(`Fetched ${data.length} sessions`, data.map(s => ({
          id: s.id.slice(0, 8),
          profile: s.profile_name,
          messages: s.message_count,
          title: s.title?.slice(0, 30)
        })))
        setSessions(data)
      } catch (error) {
        console.error('Failed to fetch sessions:', error)
      } finally {
        setSessionsLoading(false)
      }
    }

    void fetchSessions()
  }, [connectionStatus])

  // Helper to refresh sessions in background (no loading state, uses transition)
  const refreshSessionsInBackground = useCallback(async () => {
    if (connectionStatus !== 'online') return
    try {
      const data = await listSessions()
      // Use startTransition to mark this as non-urgent update
      startTransition(() => {
        setSessions(data)
      })
    } catch (error) {
      console.error('Failed to refresh sessions:', error)
    }
  }, [connectionStatus])

  // Refresh sessions when generation completes
  useEffect(() => {
    // Detect transition from generating to not generating
    const wasGenerating = prevGenerationInProgress.current
    prevGenerationInProgress.current = generationInProgress

    if (wasGenerating && !generationInProgress && connectionStatus === 'online') {
      // Generation just completed - refresh session list to update message counts
      debug('Generation completed, refreshing sessions in background...')
      void refreshSessionsInBackground()
    }
  }, [generationInProgress, connectionStatus, refreshSessionsInBackground])

  // Load current session from backend when ID changes
  useEffect(() => {
    if (connectionStatus !== 'online' || !currentSessionId) {
      setCurrentSession(null)
      return
    }

    // Capture current session ID for the async function
    const sessionIdToLoad = currentSessionId

    async function loadSession() {
      try {
        const session = await apiGetSession(sessionIdToLoad)
        setCurrentSession(session)
      } catch (error) {
        console.error('Failed to load session:', error)
        // Session doesn't exist, clear it
        setCurrentSessionId(null)
        setCurrentSession(null)
      }
    }

    void loadSession()
  }, [connectionStatus, currentSessionId, setCurrentSessionId])

  // Create initial session if none exists
  useEffect(() => {
    if (connectionStatus !== 'online' || currentSessionId || sessionsLoading) return

    async function createInitialSession() {
      try {
        const session = await apiCreateSession({ profile_name: selectedProfile })
        setCurrentSessionId(session.id)
        setCurrentSession(session)
        // Refresh sessions list in background
        void refreshSessionsInBackground()
      } catch (error) {
        console.error('Failed to create initial session:', error)
      }
    }

    void createInitialSession()
  }, [connectionStatus, currentSessionId, selectedProfile, sessionsLoading, setCurrentSessionId, refreshSessionsInBackground])

  // Global keyboard shortcut for command palette
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen(prev => !prev)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // --- Actions ---

  const selectProfile = useCallback(async (name: string) => {
    debug(`Selecting profile: ${name}`)
    setSelectedProfile(name)
    setChatError(null)

    if (connectionStatus === 'online') {
      try {
        // First, check if there's already an empty session for this profile
        // This prevents "Untitled session" accumulation when switching profiles rapidly
        const existingEmptySession = sessions.find(
          s => s.profile_name === name && s.message_count === 0
        )

        if (existingEmptySession) {
          // Reuse existing empty session
          debug(`Reusing existing empty session: ${existingEmptySession.id.slice(0, 8)}`)
          const session = await apiGetSession(existingEmptySession.id)
          setCurrentSessionId(session.id)
          setCurrentSession(session)
        } else {
          // Create new session only if no empty session exists for this profile
          debug(`Creating new session for profile ${name}...`)
          const session = await apiCreateSession({ profile_name: name })
          debug(`Created session: ${session.id.slice(0, 8)}`)
          setCurrentSessionId(session.id)
          setCurrentSession(session)
          // Refresh sessions list in background
          void refreshSessionsInBackground()
        }
      } catch (error) {
        console.error('Failed to create/load session for profile:', error)
      }
    }
  }, [connectionStatus, sessions, setSelectedProfile, setCurrentSessionId, refreshSessionsInBackground])

  const sendMessage = useCallback(async (content: string) => {
    if (!currentSession || connectionStatus !== 'online') {
      debug(`sendMessage blocked: currentSession=${!!currentSession}, connectionStatus=${connectionStatus}`)
      return
    }
    // Don't block if already loading - allow queueing
    if (chatLoading) {
      debug('Generation already in progress, request will be queued')
    }

    debug(`📤 Sending message to session ${currentSession.id.slice(0, 8)}: "${content.slice(0, 50)}..."`)

    // Optimistic update: add user message immediately
    const tempUserMessage: SessionMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now() / 1000,
      tool_calls: [],
      tool_results: [],
    }

    debug('Optimistic update: adding temp user message')
    setCurrentSession(prev => prev ? {
      ...prev,
      messages: [...prev.messages, tempUserMessage],
    } : null)

    setChatLoading(true)
    setGenerationInProgress(true)
    setChatError(null)

    const startTime = Date.now()
    try {
      debug('Calling sendSessionChat API...')
      // Send message via session chat endpoint (uses backend semaphore)
      const result = await sendSessionChat(currentSession.id, {
        message: content,
        model_size: 'large',
      })

      const elapsed = Date.now() - startTime
      debug(`📥 Response received in ${elapsed}ms:`, {
        sessionMessages: result.session.messages.length,
        queueStats: result.queue_stats,
        toolCalls: result.response.tool_calls?.length ?? 0,
      })

      // Update current session with authoritative response from server
      setCurrentSession(result.session)

      // Refresh sessions list in background (title may have changed)
      debug('Refreshing sessions list in background after response...')
      void refreshSessionsInBackground()
    } catch (error) {
      debug('❌ sendMessage error:', error)
      let errorMessage = 'Failed to send message'
      if (error instanceof ApiError) {
        if (error.status === 503) {
          errorMessage = 'Model is busy with another request. Please wait...'
        } else {
          errorMessage = error.detail ?? error.message
        }
        debug(`API error: status=${error.status}, message=${errorMessage}`)
      } else if (error instanceof NetworkError) {
        errorMessage = 'Connection lost. Please check if the daemon is running.'
        debug('Network error, going offline')
        setConnectionStatus('offline')
      }
      setChatError(errorMessage)
      // Revert optimistic update on error
      debug('Reverting optimistic update')
      setCurrentSession(prev => prev ? {
        ...prev,
        messages: prev.messages.filter(m => m.id !== tempUserMessage.id),
      } : null)
    } finally {
      debug('sendMessage complete, resetting loading states')
      setChatLoading(false)
      setGenerationInProgress(false)
    }
  }, [currentSession, chatLoading, connectionStatus])

  const newSession = useCallback(async () => {
    if (connectionStatus !== 'online') return

    setChatError(null)
    try {
      const session = await apiCreateSession({ profile_name: selectedProfile })
      setCurrentSessionId(session.id)
      setCurrentSession(session)
      // Refresh sessions list in background
      void refreshSessionsInBackground()
    } catch (error) {
      console.error('Failed to create new session:', error)
    }
  }, [connectionStatus, selectedProfile, setCurrentSessionId, refreshSessionsInBackground])

  const switchSession = useCallback(async (sessionId: string) => {
    if (connectionStatus !== 'online') return

    debug(`Switching to session: ${sessionId.slice(0, 8)}`)
    setChatError(null)
    try {
      const session = await apiGetSession(sessionId)
      debug(`Loaded session: ${session.messages.length} messages, profile=${session.profile_name}`)
      setCurrentSessionId(session.id)
      setCurrentSession(session)
      // Update selected profile to match session
      if (session.profile_name !== selectedProfile) {
        debug(`Updating profile: ${selectedProfile} -> ${session.profile_name}`)
        setSelectedProfile(session.profile_name)
      }
    } catch (error) {
      console.error('Failed to switch session:', error)
    }
  }, [connectionStatus, selectedProfile, setCurrentSessionId, setSelectedProfile])

  const clearError = useCallback(() => {
    setChatError(null)
  }, [])

  const openPalette = useCallback(() => {
    setPaletteOpen(true)
  }, [])

  const closePalette = useCallback(() => {
    setPaletteOpen(false)
  }, [])

  const addRecentCommand = useCallback((commandId: string) => {
    setRecentCommands(prev => {
      const filtered = prev.filter(id => id !== commandId)
      return [commandId, ...filtered].slice(0, 10)
    })
  }, [setRecentCommands])

  // --- Build Commands ---

  const commands = useMemo((): Command[] => {
    const cmds: Command[] = []

    // Actions
    cmds.push({
      id: 'new-chat',
      type: 'action',
      label: 'New Chat',
      description: 'Start a fresh conversation',
      shortcut: '⌘N',
      onExecute: () => {
        void newSession()
        addRecentCommand('new-chat')
      },
    })

    // Profiles
    profiles.forEach(profile => {
      cmds.push({
        id: `profile-${profile.name}`,
        type: 'profile',
        label: `Switch to ${profile.name}`,
        description: `${profile.tool_names.length} tools available`,
        onExecute: () => {
          void selectProfile(profile.name)
          addRecentCommand(`profile-${profile.name}`)
        },
      })
    })

    // Recent sessions
    sessions.slice(0, 5).forEach(session => {
      cmds.push({
        id: `session-${session.id}`,
        type: 'action',
        label: session.title ?? 'Untitled session',
        description: `${session.profile_name} • ${session.message_count} messages`,
        onExecute: () => {
          void switchSession(session.id)
          addRecentCommand(`session-${session.id}`)
        },
      })
    })

    // Tools (only if current profile has tools)
    profileTools.forEach(tool => {
      cmds.push({
        id: `tool-${tool.name}`,
        type: 'tool',
        label: tool.name,
        description: tool.description.slice(0, 80),
        onExecute: () => {
          // Could open tool invocation modal, for now just focus input
          addRecentCommand(`tool-${tool.name}`)
        },
      })
    })

    return cmds
  }, [profiles, profileTools, sessions, selectProfile, newSession, switchSession, addRecentCommand])

  // --- Convert Session to ChatMessage array for display ---

  const chatMessages = useMemo((): ChatMessage[] => {
    if (!currentSession) return []
    return currentSession.messages.map(msg => ({
      id: msg.id,
      role: msg.role as 'user' | 'assistant',
      content: msg.content,
      timestamp: msg.timestamp * 1000, // Convert to milliseconds for JS Date
      toolCalls: msg.tool_calls,
      toolResults: msg.tool_results,
    }))
  }, [currentSession])

  // Memoize the combined session object to prevent new references on unrelated state changes
  const currentSessionWithMessages = useMemo(() => {
    if (!currentSession) return null
    return {
      ...currentSession,
      messages: chatMessages,
    }
  }, [currentSession, chatMessages])

  // --- Return State & Actions ---

  return {
    // State
    connectionStatus,
    generationInProgress,
    generatingSessionId,
    queuedSessionIds,
    profiles,
    selectedProfile,
    profileTools,
    sessions,
    currentSession: currentSessionWithMessages,
    chatLoading,
    chatError,
    paletteOpen,
    recentCommands,
    profilesLoading,
    toolsLoading,
    sessionsLoading,
    commands,

    // Actions
    selectProfile,
    sendMessage,
    clearError,
    openPalette,
    closePalette,
    newSession,
    switchSession,
  }
}
