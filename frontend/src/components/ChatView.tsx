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

import { useState, useRef, useEffect, useCallback, FormEvent } from 'react'
import type { ToolCallInfo, ToolResultInfo } from '../api'
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
}

// --- Component ---

export function ChatView({
  messages,
  onSendMessage,
  profileName,
  loading = false,
  error,
  onClearError,
}: ChatViewProps) {
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Handle submit
  const handleSubmit = useCallback(async (e?: FormEvent) => {
    e?.preventDefault()
    const message = input.trim()
    if (!message || loading) return

    setInput('')
    await onSendMessage(message)
  }, [input, loading, onSendMessage])

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
            {loading && <LoadingIndicator />}
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
            disabled={loading}
            aria-label="Message input"
          />
          <button
            type="submit"
            className="chat-send-button"
            disabled={!input.trim() || loading}
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

function MessageBubble({ message }: { message: ChatMessage }) {
  const [expandedToolCall, setExpandedToolCall] = useState<number | null>(null)

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
              <div key={idx} className="chat-tool-call">
                <button
                  className="chat-tool-call-header"
                  onClick={() => setExpandedToolCall(expandedToolCall === idx ? null : idx)}
                  aria-expanded={expandedToolCall === idx}
                >
                  <span className="chat-tool-call-icon">⚡</span>
                  <span className="chat-tool-call-name">{tc.name}</span>
                  <span className="chat-tool-call-chevron">
                    {expandedToolCall === idx ? '−' : '+'}
                  </span>
                </button>

                {expandedToolCall === idx && (
                  <div className="chat-tool-call-body">
                    <div className="chat-tool-call-section">
                      <span className="chat-tool-call-label">Arguments</span>
                      <pre className="chat-tool-call-code">
                        {JSON.stringify(tc.arguments, null, 2)}
                      </pre>
                    </div>

                    {message.toolResults?.[idx] && (
                      <div className="chat-tool-call-section">
                        <span className="chat-tool-call-label">Result</span>
                        <pre className="chat-tool-call-code">
                          {typeof message.toolResults[idx].result === 'string'
                            ? message.toolResults[idx].result
                            : JSON.stringify(message.toolResults[idx].result, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

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

function LoadingIndicator() {
  return (
    <div className="chat-message chat-message-assistant">
      <div className="chat-message-avatar">Q</div>
      <div className="chat-message-content">
        <div className="chat-loading">
          <span className="chat-loading-dot" />
          <span className="chat-loading-dot" />
          <span className="chat-loading-dot" />
        </div>
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
