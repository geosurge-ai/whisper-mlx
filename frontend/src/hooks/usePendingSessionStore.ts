/**
 * usePendingSessionStore - Manages pending session state for optimistic updates
 *
 * This hook provides a stable store for sessions with pending optimistic updates
 * (user messages not yet confirmed by the server). It prevents race conditions
 * when switching between sessions during generation.
 */

import { useRef, useCallback, useMemo } from 'react'
import type { Session } from '../api'

export interface PendingSessionState {
  session: Session
  pendingMessageIds: Set<string>  // IDs of optimistic messages not yet on server
  isGenerating: boolean
}

export interface PendingSessionStore {
  /** Check if a session has pending state */
  has: (sessionId: string) => boolean

  /** Get pending session state (returns undefined if not found) */
  get: (sessionId: string) => PendingSessionState | undefined

  /** Record an optimistic message for a session */
  recordOptimisticMessage: (sessionId: string, session: Session, messageId: string) => void

  /** Apply SSE complete event - stores final session state */
  applyComplete: (sessionId: string, finalSession: Session) => void

  /** Apply SSE error - removes the pending message from cached state */
  applyError: (sessionId: string, messageIdToRemove: string) => Session | undefined

  /** Clear pending state for a session (called after successful server fetch) */
  clear: (sessionId: string) => void

  /** Get session for hydration - returns cached if pending, otherwise undefined */
  getForHydration: (sessionId: string) => Session | undefined

  /** Mark a session as no longer generating (but keep cache for hydration) */
  markComplete: (sessionId: string) => void
}

/**
 * Hook that provides a stable pending session store
 */
export function usePendingSessionStore(): PendingSessionStore {
  const store = useRef<Map<string, PendingSessionState>>(new Map())

  const has = useCallback((sessionId: string): boolean => {
    return store.current.has(sessionId)
  }, [])

  const get = useCallback((sessionId: string): PendingSessionState | undefined => {
    return store.current.get(sessionId)
  }, [])

  const recordOptimisticMessage = useCallback((
    sessionId: string,
    session: Session,
    messageId: string
  ) => {
    const existing = store.current.get(sessionId)
    const pendingMessageIds = existing?.pendingMessageIds ?? new Set()
    pendingMessageIds.add(messageId)

    store.current.set(sessionId, {
      session,
      pendingMessageIds,
      isGenerating: true,
    })
  }, [])

  const applyComplete = useCallback((sessionId: string, finalSession: Session) => {
    const existing = store.current.get(sessionId)
    if (existing) {
      // Clear pending message IDs since server now has them
      store.current.set(sessionId, {
        session: finalSession,
        pendingMessageIds: new Set(),
        isGenerating: false,
      })
    }
  }, [])

  const applyError = useCallback((sessionId: string, messageIdToRemove: string): Session | undefined => {
    const existing = store.current.get(sessionId)
    if (!existing) return undefined

    const updatedMessages = existing.session.messages.filter(m => m.id !== messageIdToRemove)
    const updatedSession = { ...existing.session, messages: updatedMessages }
    
    existing.pendingMessageIds.delete(messageIdToRemove)
    
    store.current.set(sessionId, {
      session: updatedSession,
      pendingMessageIds: existing.pendingMessageIds,
      isGenerating: existing.isGenerating,
    })

    return updatedSession
  }, [])

  const clear = useCallback((sessionId: string) => {
    store.current.delete(sessionId)
  }, [])

  const getForHydration = useCallback((sessionId: string): Session | undefined => {
    const pending = store.current.get(sessionId)
    return pending?.session
  }, [])

  const markComplete = useCallback((sessionId: string) => {
    const existing = store.current.get(sessionId)
    if (existing) {
      store.current.set(sessionId, {
        ...existing,
        isGenerating: false,
      })
    }
  }, [])

  // IMPORTANT: Memoize the returned object to prevent infinite re-render loops
  // when this store is used in useEffect dependency arrays
  return useMemo(() => ({
    has,
    get,
    recordOptimisticMessage,
    applyComplete,
    applyError,
    clear,
    getForHydration,
    markComplete,
  }), [has, get, recordOptimisticMessage, applyComplete, applyError, clear, getForHydration, markComplete])
}
