/**
 * useAppState - Main application state hook
 *
 * Combines all state management with backend session persistence.
 * Sessions are stored on the backend, localStorage serves as cache.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useLocalStorage } from './useLocalStorage'
import type { ProfileInfo, ToolInfo, Session, SessionSummary } from '../api'
import {
  getHealth,
  getProfiles,
  getProfileTools,
  listSessions,
  createSession as apiCreateSession,
  getSession as apiGetSession,
  sendSessionChat,
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

  // --- Effects ---

  // Check connection on mount and poll for generation status
  useEffect(() => {
    async function checkConnection() {
      setConnectionStatus('checking')
      try {
        const health = await getHealth()
        setConnectionStatus('online')
        setGenerationInProgress(health.generation_in_progress)
      } catch {
        setConnectionStatus('offline')
      }
    }

    void checkConnection()

    // Recheck every 10s (more frequent to track generation status)
    const interval = setInterval(() => void checkConnection(), 10000)
    return () => clearInterval(interval)
  }, [])

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

  // Fetch sessions from backend when online
  useEffect(() => {
    if (connectionStatus !== 'online') return

    async function fetchSessions() {
      setSessionsLoading(true)
      try {
        const data = await listSessions()
        setSessions(data)
      } catch (error) {
        console.error('Failed to fetch sessions:', error)
      } finally {
        setSessionsLoading(false)
      }
    }

    void fetchSessions()
  }, [connectionStatus])

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
        // Refresh sessions list
        const data = await listSessions()
        setSessions(data)
      } catch (error) {
        console.error('Failed to create initial session:', error)
      }
    }

    void createInitialSession()
  }, [connectionStatus, currentSessionId, selectedProfile, sessionsLoading, setCurrentSessionId])

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
    setSelectedProfile(name)
    setChatError(null)

    // Create new session for new profile
    if (connectionStatus === 'online') {
      try {
        const session = await apiCreateSession({ profile_name: name })
        setCurrentSessionId(session.id)
        setCurrentSession(session)
        // Refresh sessions list
        const data = await listSessions()
        setSessions(data)
      } catch (error) {
        console.error('Failed to create session for profile:', error)
      }
    }
  }, [connectionStatus, setSelectedProfile, setCurrentSessionId])

  const sendMessage = useCallback(async (content: string) => {
    if (!currentSession || chatLoading || connectionStatus !== 'online') return

    setChatLoading(true)
    setChatError(null)

    try {
      // Send message via session chat endpoint (uses backend semaphore)
      const result = await sendSessionChat(currentSession.id, {
        message: content,
        model_size: 'large',
      })

      // Update current session with response
      setCurrentSession(result.session)

      // Refresh sessions list (title may have changed)
      const data = await listSessions()
      setSessions(data)
    } catch (error) {
      let errorMessage = 'Failed to send message'
      if (error instanceof ApiError) {
        if (error.status === 503) {
          errorMessage = 'Model is busy with another request. Please wait...'
        } else {
          errorMessage = error.detail ?? error.message
        }
      } else if (error instanceof NetworkError) {
        errorMessage = 'Connection lost. Please check if the daemon is running.'
        setConnectionStatus('offline')
      }
      setChatError(errorMessage)
    } finally {
      setChatLoading(false)
    }
  }, [currentSession, chatLoading, connectionStatus])

  const newSession = useCallback(async () => {
    if (connectionStatus !== 'online') return

    setChatError(null)
    try {
      const session = await apiCreateSession({ profile_name: selectedProfile })
      setCurrentSessionId(session.id)
      setCurrentSession(session)
      // Refresh sessions list
      const data = await listSessions()
      setSessions(data)
    } catch (error) {
      console.error('Failed to create new session:', error)
    }
  }, [connectionStatus, selectedProfile, setCurrentSessionId])

  const switchSession = useCallback(async (sessionId: string) => {
    if (connectionStatus !== 'online') return

    setChatError(null)
    try {
      const session = await apiGetSession(sessionId)
      setCurrentSessionId(session.id)
      setCurrentSession(session)
      // Update selected profile to match session
      if (session.profile_name !== selectedProfile) {
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

  // --- Return State & Actions ---

  return {
    // State
    connectionStatus,
    generationInProgress,
    profiles,
    selectedProfile,
    profileTools,
    sessions,
    currentSession: currentSession ? {
      ...currentSession,
      messages: chatMessages,
    } : null,
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
