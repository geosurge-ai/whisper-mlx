/**
 * CollapsibleResult - Pretty-printed JSON in a collapsible panel
 *
 * Used to display tool call arguments and results in a clean, expandable format.
 * Special handling for:
 * - Code fields (displayed with proper formatting)
 * - Images (rendered as actual images from base64 data URIs)
 */

import { useState, useMemo } from 'react'
import './CollapsibleResult.css'

// --- Helper Types ---

interface ImageData {
  filename: string
  data: string // data URI
}

interface ParsedResult {
  success?: boolean
  stdout?: string
  stderr?: string
  error?: string | null
  images?: ImageData[]
  [key: string]: unknown
}

// --- Helper Functions ---

/**
 * Parse a value that might be a JSON string
 */
function parseJsonValue(value: unknown): unknown {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return value
    }
  }
  return value
}

/**
 * Format a value for display, with special handling for code fields
 */
function formatForDisplay(value: unknown, excludeKeys: string[] = []): string {
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'object' && value !== null) {
    // Filter out excluded keys
    const filtered = Object.fromEntries(
      Object.entries(value).filter(([k]) => !excludeKeys.includes(k))
    )
    if (Object.keys(filtered).length === 0) return ''
    return JSON.stringify(filtered, null, 2)
  }
  return JSON.stringify(value, null, 2)
}

// --- Components ---

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

  const formattedData = useMemo(() => {
    const parsed = parseJsonValue(data)
    return formatForDisplay(parsed)
  }, [data])

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
 * Display tool arguments with special handling for code fields
 */
function ToolArgsDisplay({ args }: { args: Record<string, unknown> }) {
  // Check if there's a 'code' field that should be displayed specially
  const hasCode = 'code' in args && typeof args.code === 'string'
  const codeValue = hasCode ? (args.code as string) : null
  
  // Get other args (excluding code)
  const otherArgs = useMemo(() => {
    if (!hasCode) return args
    return Object.fromEntries(
      Object.entries(args).filter(([k]) => k !== 'code')
    )
  }, [args, hasCode])

  const hasOtherArgs = Object.keys(otherArgs).length > 0

  return (
    <div className="tool-args-display">
      {/* Show non-code args as formatted JSON */}
      {hasOtherArgs && (
        <pre className="tool-call-result-code tool-args-json">
          {JSON.stringify(otherArgs, null, 2)}
        </pre>
      )}
      {/* Show code with proper formatting */}
      {codeValue && (
        <div className="tool-args-code">
          <span className="tool-args-code-label">code:</span>
          <pre className="tool-args-code-block">{codeValue}</pre>
        </div>
      )}
    </div>
  )
}

/**
 * Display tool result with special handling for images and stdout
 */
function ToolResultDisplay({ result }: { result: unknown }) {
  const parsed = useMemo((): ParsedResult => {
    const value = parseJsonValue(result)
    if (typeof value === 'object' && value !== null) {
      return value as ParsedResult
    }
    return { stdout: String(value) }
  }, [result])

  const hasImages = Array.isArray(parsed.images) && parsed.images.length > 0
  const hasStdout = typeof parsed.stdout === 'string' && parsed.stdout.trim()
  const hasError = typeof parsed.error === 'string' && parsed.error.trim()
  const hasStderr = typeof parsed.stderr === 'string' && parsed.stderr.trim()

  // Keys to exclude from the generic display (they're handled specially)
  const specialKeys = ['images', 'stdout', 'stderr', 'error', 'success']
  const otherData = formatForDisplay(parsed, specialKeys)

  return (
    <div className="tool-result-display">
      {/* Show images first */}
      {hasImages && (
        <div className="tool-result-images">
          {parsed.images!.map((img, i) => (
            <figure key={i} className="tool-result-image">
              <img src={img.data} alt={img.filename} />
              <figcaption>{img.filename}</figcaption>
            </figure>
          ))}
        </div>
      )}

      {/* Show error if present */}
      {hasError && (
        <div className="tool-result-error">
          <span className="tool-result-error-label">Error:</span>
          <pre className="tool-result-error-text">{parsed.error}</pre>
        </div>
      )}

      {/* Show stdout if present */}
      {hasStdout && (
        <div className="tool-result-stdout">
          <span className="tool-result-stdout-label">Output:</span>
          <pre className="tool-result-stdout-text">{parsed.stdout}</pre>
        </div>
      )}

      {/* Show stderr if present (and no error) */}
      {hasStderr && !hasError && (
        <div className="tool-result-stderr">
          <span className="tool-result-stderr-label">Stderr:</span>
          <pre className="tool-result-stderr-text">{parsed.stderr}</pre>
        </div>
      )}

      {/* Show other data as formatted JSON */}
      {otherData && (
        <pre className="tool-call-result-code">{otherData}</pre>
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

  // Check if result has images
  const hasImages = useMemo(() => {
    if (result === undefined) return false
    const parsed = parseJsonValue(result)
    if (typeof parsed === 'object' && parsed !== null) {
      const images = (parsed as ParsedResult).images
      return Array.isArray(images) && images.length > 0
    }
    return false
  }, [result])

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
        {hasImages && (
          <span className="tool-call-result-badge tool-call-result-badge-image">📊 images</span>
        )}
        <span className="tool-call-result-chevron">
          {expanded ? '−' : '+'}
        </span>
      </button>

      {expanded && (
        <div className="tool-call-result-body">
          <div className="tool-call-result-section">
            <span className="tool-call-result-label">Arguments</span>
            <ToolArgsDisplay args={args} />
          </div>

          {result !== undefined && (
            <div className="tool-call-result-section">
              <span className="tool-call-result-label">Result</span>
              <ToolResultDisplay result={result} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
