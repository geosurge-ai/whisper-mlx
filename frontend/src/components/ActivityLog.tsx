/**
 * ActivityLog - Collapsible panel showing real-time generation activity
 *
 * Displays SSE events during LLM generation:
 * - Round starts (thinking)
 * - Tool executions
 * - Completion/errors
 */

import { useState, useRef, useEffect } from 'react'
import type { ActivityEvent, GenerationActivity } from '../hooks/useAppState'
import './ActivityLog.css'

interface ActivityLogProps {
  activity: GenerationActivity
  onClear?: () => void
}

export function ActivityLog({ activity, onClear }: ActivityLogProps) {
  const [expanded, setExpanded] = useState(true)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (expanded) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [activity.events, expanded])

  // Don't render if no activity and idle
  if (activity.status === 'idle' && activity.events.length === 0) {
    return null
  }

  const getStatusIcon = () => {
    switch (activity.status) {
      case 'thinking':
        return '🧠'
      case 'tool':
        return '⚡'
      default:
        return '✓'
    }
  }

  const getStatusText = () => {
    if (activity.status === 'thinking') {
      return activity.currentRound > 0
        ? `Thinking (round ${activity.currentRound}/${activity.maxRounds})...`
        : 'Thinking...'
    }
    if (activity.status === 'tool' && activity.currentTool) {
      return `Running ${activity.currentTool}...`
    }
    return 'Idle'
  }

  return (
    <div className={`activity-log ${expanded ? 'expanded' : 'collapsed'}`}>
      <button
        className="activity-log-header"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls="activity-log-content"
      >
        <span className="activity-log-status">
          <span className={`activity-log-icon ${activity.status !== 'idle' ? 'active' : ''}`}>
            {getStatusIcon()}
          </span>
          <span className="activity-log-text">{getStatusText()}</span>
        </span>
        <span className="activity-log-actions">
          {activity.events.length > 0 && (
            <span className="activity-log-count">{activity.events.length} events</span>
          )}
          <span className="activity-log-chevron">{expanded ? '▼' : '▶'}</span>
        </span>
      </button>

      {expanded && (
        <div id="activity-log-content" className="activity-log-content">
          {activity.events.length === 0 ? (
            <div className="activity-log-empty">Waiting for events...</div>
          ) : (
            <>
              <ul className="activity-log-events">
                {activity.events.map((event, idx) => (
                  <ActivityEventItem key={idx} event={event} />
                ))}
                <div ref={logEndRef} />
              </ul>
              {onClear && activity.status === 'idle' && (
                <button className="activity-log-clear" onClick={onClear}>
                  Clear log
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Pretty-prints tool arguments, with special handling for code fields
 */
function ToolArgsDisplay({ args }: { args: Record<string, unknown> }) {
  // Check if there's a 'code' field that should be displayed specially
  const hasCode = 'code' in args && typeof args.code === 'string'
  const codeValue = hasCode ? (args.code as string) : null
  const otherArgs = hasCode
    ? Object.fromEntries(Object.entries(args).filter(([k]) => k !== 'code'))
    : args

  return (
    <>
      {/* Show non-code args as formatted JSON */}
      {Object.keys(otherArgs).length > 0 && (
        <pre className="activity-event-args-json">
          {JSON.stringify(otherArgs, null, 2)}
        </pre>
      )}
      {/* Show code with proper formatting */}
      {codeValue && (
        <div className="activity-event-code">
          <div className="activity-event-code-label">code:</div>
          <pre className="activity-event-code-block">{codeValue}</pre>
        </div>
      )}
    </>
  )
}

function ActivityEventItem({ event }: { event: ActivityEvent }) {
  const [showDetails, setShowDetails] = useState(false)

  const getIcon = () => {
    switch (event.type) {
      case 'round_start':
        return '🔄'
      case 'generating':
        return '🧠'
      case 'thinking':
        return '💭'
      case 'tool_start':
        return '▶️'
      case 'tool_end':
        return '✅'
      case 'complete':
        return '🎉'
      case 'error':
        return '❌'
      default:
        return '•'
    }
  }

  const getMessage = () => {
    switch (event.type) {
      case 'round_start':
        return `Round ${event.round}/${event.maxRounds} started`
      case 'generating':
        return `Model generating...`
      case 'thinking':
        return `LLM reasoning`
      case 'tool_start':
        return `${event.toolName}`
      case 'tool_end':
        return `${event.toolName} complete`
      case 'complete':
        return 'Generation complete'
      case 'error':
        return 'Error occurred'
      default:
        return event.type
    }
  }

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp)
    // Guard against invalid dates
    if (isNaN(date.getTime())) {
      return '--:--:--'
    }
    return date.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  // Check if this event has expandable content
  const hasExpandableContent = 
    (event.type === 'tool_start' && event.toolArgs) ||
    (event.type === 'tool_end' && event.toolResult) ||
    (event.type === 'thinking' && event.thinkingContent)

  return (
    <li className={`activity-event activity-event-${event.type}`}>
      <span className="activity-event-icon">{getIcon()}</span>
      <span className="activity-event-message">{getMessage()}</span>
      <span className="activity-event-time">{formatTime(event.timestamp)}</span>

      {hasExpandableContent && (
        <>
          <button
            className="activity-event-args-toggle"
            onClick={() => setShowDetails(!showDetails)}
            aria-expanded={showDetails}
          >
            {showDetails ? '−' : '+'}
          </button>
          {showDetails && (
            <div className="activity-event-args">
              {/* Tool start: show arguments */}
              {event.type === 'tool_start' && event.toolArgs && (
                <ToolArgsDisplay args={event.toolArgs} />
              )}
              {/* Tool end: show result */}
              {event.type === 'tool_end' && event.toolResult && (
                <div className="activity-event-result">
                  <div className="activity-event-result-label">Result:</div>
                  <pre className="activity-event-result-text">{event.toolResult}</pre>
                </div>
              )}
              {/* Thinking: show LLM reasoning */}
              {event.type === 'thinking' && event.thinkingContent && (
                <div className="activity-event-thinking">
                  <pre className="activity-event-thinking-text">{event.thinkingContent}</pre>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </li>
  )
}
