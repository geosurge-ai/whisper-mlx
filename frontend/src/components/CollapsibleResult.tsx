/**
 * CollapsibleResult - Pretty-printed JSON in a collapsible panel
 *
 * Used to display tool call arguments and results in a clean, expandable format.
 */

import { useState } from 'react'
import './CollapsibleResult.css'

interface CollapsibleResultProps {
  title: string
  icon?: string
  data: unknown
  defaultExpanded?: boolean
}

export function CollapsibleResult({
  title,
  icon = '⚡',
  data,
  defaultExpanded = false,
}: CollapsibleResultProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const formatData = (value: unknown): string => {
    if (typeof value === 'string') {
      // Try to parse as JSON for pretty printing
      try {
        const parsed = JSON.parse(value)
        return JSON.stringify(parsed, null, 2)
      } catch {
        // Not JSON, return as-is but handle long strings
        return value
      }
    }
    return JSON.stringify(value, null, 2)
  }

  const formattedData = formatData(data)
  const previewLength = 60
  const preview = formattedData.length > previewLength
    ? formattedData.slice(0, previewLength) + '...'
    : formattedData

  return (
    <div className={`collapsible-result ${expanded ? 'expanded' : ''}`}>
      <button
        className="collapsible-result-header"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span className="collapsible-result-icon">{icon}</span>
        <span className="collapsible-result-title">{title}</span>
        {!expanded && (
          <span className="collapsible-result-preview">{preview}</span>
        )}
        <span className="collapsible-result-chevron">
          {expanded ? '−' : '+'}
        </span>
      </button>

      {expanded && (
        <div className="collapsible-result-body">
          <pre className="collapsible-result-code">{formattedData}</pre>
        </div>
      )}
    </div>
  )
}

/**
 * ToolCallResult - Specialized collapsible for tool calls with arguments and results
 */
interface ToolCallResultProps {
  toolName: string
  args: Record<string, unknown>
  result?: unknown
  defaultExpanded?: boolean
}

export function ToolCallResult({
  toolName,
  args,
  result,
  defaultExpanded = false,
}: ToolCallResultProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const formatValue = (value: unknown): string => {
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value)
        return JSON.stringify(parsed, null, 2)
      } catch {
        return value
      }
    }
    return JSON.stringify(value, null, 2)
  }

  return (
    <div className={`tool-call-result ${expanded ? 'expanded' : ''}`}>
      <button
        className="tool-call-result-header"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span className="tool-call-result-icon">⚡</span>
        <span className="tool-call-result-name">{toolName}</span>
        {result !== undefined && (
          <span className="tool-call-result-badge">has result</span>
        )}
        <span className="tool-call-result-chevron">
          {expanded ? '−' : '+'}
        </span>
      </button>

      {expanded && (
        <div className="tool-call-result-body">
          <div className="tool-call-result-section">
            <span className="tool-call-result-label">Arguments</span>
            <pre className="tool-call-result-code">
              {formatValue(args)}
            </pre>
          </div>

          {result !== undefined && (
            <div className="tool-call-result-section">
              <span className="tool-call-result-label">Result</span>
              <pre className="tool-call-result-code">
                {formatValue(result)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
