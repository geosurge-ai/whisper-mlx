/**
 * ChatView - Main chat interface
 *
 * Features:
 * - Message transcript with user/assistant bubbles
 * - Tool call display with expandable results
 * - Composer with send button and keyboard shortcut
 * - Loading states and error handling
 * - Bauhaus-inspired design with generous spacing
 */

import { useState, useRef, useEffect, useCallback, FormEvent, memo } from 'react'
import type { ToolCallInfo, ToolResultInfo } from '../api'
import type { GenerationActivity } from '../hooks/useAppState'
import { ActivityLog } from './ActivityLog'
import { ToolCallResult } from './CollapsibleResult'
import './ChatView.css'

// --- Types ---

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCallInfo[]
  toolResults?: ToolResultInfo[]
  timestamp: number
}

interface ChatViewProps {
  messages: ChatMessage[]
  onSendMessage: (message: string) => Promise<void>
  profileName: string
  loading?: boolean
  error?: string | null
  onClearError?: () => void
  // Generation activity (real-time SSE updates)
  activity?: GenerationActivity
  onClearActivityLog?: () => void
  // Generation status for cross-session awareness
  currentSessionId?: string | null
  generatingSessionId?: string | null
  generatingSessionTitle?: string | null
  onGoToGeneratingSession?: () => void
}

// --- Component ---

export function ChatView({
  messages,
  onSendMessage,
  profileName,
  loading = false,
  error,
  onClearError,
  activity,
  onClearActivityLog,
  currentSessionId,
  generatingSessionId,
  generatingSessionTitle,
  onGoToGeneratingSession,
}: ChatViewProps) {
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const prevMessagesRef = useRef<{ sessionId: string | null | undefined; count: number; lastId: string | null }>({
    sessionId: null,
    count: 0,
    lastId: null,
  })

  // Determine if THIS session is the one generating (should block input)
  // vs another session generating (should allow queueing)
  const isThisSessionGenerating = loading && generatingSessionId === currentSessionId

  // Auto-scroll to bottom only when:
  // 1. New messages are added to the SAME session
  // 2. User switches to a different session (scroll once to show latest)
  useEffect(() => {
    const prev = prevMessagesRef.current
    const currentCount = messages.length
    const currentLastId = messages[messages.length - 1]?.id ?? null
    const sessionChanged = currentSessionId !== prev.sessionId
    
    // Scroll if: session changed OR new message added (by checking last message ID)
    const shouldScroll = sessionChanged || (currentLastId !== prev.lastId && currentCount > prev.count)
    
    if (shouldScroll) {
      messagesEndRef.current?.scrollIntoView({ behavior: sessionChanged ? 'auto' : 'smooth' })
    }
    
    prevMessagesRef.current = { sessionId: currentSessionId, count: currentCount, lastId: currentLastId }
  }, [messages, currentSessionId])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Handle submit
  const handleSubmit = useCallback(async (e?: FormEvent) => {
    e?.preventDefault()
    const message = input.trim()
    if (!message || isThisSessionGenerating) return

    setInput('')
    await onSendMessage(message)
  }, [input, isThisSessionGenerating, onSendMessage])

  // Handle keyboard shortcuts
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }, [handleSubmit])

  // Auto-resize textarea
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    // Reset height to auto to get correct scrollHeight
    e.target.style.height = 'auto'
    // Set to scrollHeight, max 200px
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
  }, [])

  return (
    <div className="chat-view">
      {/* Messages Area */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <EmptyState profileName={profileName} />
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {/* Show typing animation only if THIS session is generating */}
            {loading && generatingSessionId === currentSessionId && (
              <LoadingIndicator activity={activity} />
            )}
            {/* Show "elsewhere" link if ANOTHER session is generating */}
            {generatingSessionId && generatingSessionId !== currentSessionId && (
              <GeneratingElsewhereIndicator
                sessionTitle={generatingSessionTitle}
                onNavigate={onGoToGeneratingSession}
              />
            )}
            {/* Show activity log when generating or has events */}
            {activity && (activity.status !== 'idle' || activity.events.length > 0) && (
              <ActivityLog activity={activity} onClear={onClearActivityLog} />
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Error Banner */}
      {error && (
        <div className="chat-error" role="alert">
          <span>{error}</span>
          {onClearError && (
            <button onClick={onClearError} aria-label="Dismiss error">
              ×
            </button>
          )}
        </div>
      )}

      {/* Composer */}
      <form className="chat-composer" onSubmit={handleSubmit}>
        <div className="chat-composer-inner">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder={`Message ${profileName}...`}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isThisSessionGenerating}
            aria-label="Message input"
          />
          <button
            type="submit"
            className="chat-send-button"
            disabled={!input.trim() || isThisSessionGenerating}
            aria-label="Send message"
          >
            <SendIcon />
          </button>
        </div>
        <div className="chat-composer-hint">
          <kbd>Enter</kbd> to send, <kbd>Shift+Enter</kbd> for new line
        </div>
      </form>
    </div>
  )
}

// --- Message Bubble ---
// Memoized to prevent re-renders when parent re-renders with same message data
// This preserves local state like expandedToolCall

const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`chat-message chat-message-${message.role}`}>
      <div className="chat-message-avatar">
        {message.role === 'user' ? 'U' : 'Q'}
      </div>

      <div className="chat-message-content">
        <div className="chat-message-header">
          <span className="chat-message-role">
            {message.role === 'user' ? 'You' : 'Qwen'}
          </span>
          <span className="chat-message-time">
            {formatTime(message.timestamp)}
          </span>
        </div>

        <div className="chat-message-text">
          {message.content || (message.toolCalls?.length ? '(Executing tools...)' : '')}
        </div>

        {/* Tool Calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="chat-tool-calls">
            {message.toolCalls.map((tc, idx) => (
              <ToolCallResult
                key={idx}
                toolName={tc.name}
                args={tc.arguments}
                result={message.toolResults?.[idx]?.result}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
})

// --- Empty State ---

function EmptyState({ profileName }: { profileName: string }) {
  return (
    <div className="chat-empty">
      <div className="chat-empty-icon">
        <div className="chat-empty-block chat-empty-block-1" />
        <div className="chat-empty-block chat-empty-block-2" />
        <div className="chat-empty-block chat-empty-block-3" />
      </div>
      <h2 className="chat-empty-title">Start a conversation</h2>
      <p className="chat-empty-description">
        Using the <strong>{profileName}</strong> profile.
        <br />
        Type a message below or press <kbd>⌘K</kbd> for quick actions.
      </p>
    </div>
  )
}

// --- Loading Indicator ---

function LoadingIndicator({ activity }: { activity?: GenerationActivity }) {
  const getStatusText = () => {
    if (!activity) return 'Thinking...'

    if (activity.status === 'tool' && activity.currentTool) {
      return `Running ${activity.currentTool}...`
    }

    if (activity.currentRound > 0 && activity.maxRounds > 0) {
      return `Thinking (${activity.currentRound}/${activity.maxRounds})...`
    }

    return 'Thinking...'
  }

  return (
    <div className="chat-message chat-message-assistant">
      <div className="chat-message-avatar">Q</div>
      <div className="chat-message-content">
        <div className="chat-loading">
          <span className="chat-loading-dot" />
          <span className="chat-loading-dot" />
          <span className="chat-loading-dot" />
          <span className="chat-loading-status">{getStatusText()}</span>
        </div>
      </div>
    </div>
  )
}

// --- Generating Elsewhere Indicator ---

function GeneratingElsewhereIndicator({
  sessionTitle,
  onNavigate,
}: {
  sessionTitle?: string | null
  onNavigate?: () => void
}) {
  return (
    <div className="chat-generating-elsewhere">
      <div className="chat-generating-elsewhere-content">
        <span className="chat-generating-elsewhere-icon">⏳</span>
        <span className="chat-generating-elsewhere-text">
          QweN is generating in{' '}
          {onNavigate ? (
            <button
              onClick={onNavigate}
              className="chat-generating-elsewhere-link"
            >
              {sessionTitle ?? 'another session'}
            </button>
          ) : (
            <span>{sessionTitle ?? 'another session'}</span>
          )}
        </span>
      </div>
    </div>
  )
}

// --- Icons ---

function SendIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

// --- Helpers ---

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit'
  })
}
