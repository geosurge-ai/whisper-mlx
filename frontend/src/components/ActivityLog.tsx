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

function ActivityEventItem({ event }: { event: ActivityEvent }) {
  const [showArgs, setShowArgs] = useState(false)

  const getIcon = () => {
    switch (event.type) {
      case 'round_start':
        return '🔄'
      case 'generating':
        return '🧠'
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
        return `Model thinking...`
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

  return (
    <li className={`activity-event activity-event-${event.type}`}>
      <span className="activity-event-icon">{getIcon()}</span>
      <span className="activity-event-message">{getMessage()}</span>
      <span className="activity-event-time">{formatTime(event.timestamp)}</span>

      {event.type === 'tool_start' && event.toolArgs && (
        <>
          <button
            className="activity-event-args-toggle"
            onClick={() => setShowArgs(!showArgs)}
            aria-expanded={showArgs}
          >
            {showArgs ? '−' : '+'}
          </button>
          {showArgs && (
            <pre className="activity-event-args">
              {JSON.stringify(event.toolArgs, null, 2)}
            </pre>
          )}
        </>
      )}
    </li>
  )
}
