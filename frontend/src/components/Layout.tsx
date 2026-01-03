/**
 * Layout - Bauhaus Three-Panel Shell
 *
 * Structure:
 * ┌──────────┬─────────────────────────┬──────────┐
 * │          │                         │          │
 * │   Rail   │      Main Canvas        │  Detail  │
 * │ (280px)  │       (flexible)        │ (320px)  │
 * │          │                         │          │
 * │ Profiles │                         │  Tools   │
 * │  & Nav   │                         │  Panel   │
 * │          │                         │          │
 * └──────────┴─────────────────────────┴──────────┘
 *
 * Bauhaus principles:
 * - Bold color blocks
 * - Generous whitespace (var(--space-6) minimum)
 * - Clear geometric divisions
 * - Functional hierarchy
 */

import { ReactNode } from 'react'
import { SkipLink } from './SkipLink'
import './Layout.css'

interface LayoutProps {
  rail: ReactNode
  main: ReactNode
  detail?: ReactNode
  connectionStatus: 'online' | 'offline' | 'checking'
  generationInProgress?: boolean
  generatingSessionId?: string | null
  onCommandPalette: () => void
}

export function Layout({
  rail,
  main,
  detail,
  connectionStatus,
  generationInProgress = false,
  generatingSessionId,
  onCommandPalette,
}: LayoutProps) {
  return (
    <div className="layout">
      <SkipLink />

      {/* Header Bar */}
      <header className="layout-header">
        <div className="layout-header-left">
          <div className="logo-block" />
          <h1 className="logo-text">Qwen</h1>
        </div>

        <button
          className="command-trigger"
          onClick={onCommandPalette}
          aria-label="Open command palette"
        >
          <span className="command-trigger-text">Search or command...</span>
          <kbd className="command-trigger-kbd">⌘K</kbd>
        </button>

        <div className="layout-header-right">
          <StatusIndicator 
            status={connectionStatus} 
            generationInProgress={generationInProgress}
            generatingSessionId={generatingSessionId}
          />
        </div>
      </header>

      {/* Main Content */}
      <div className="layout-body">
        <aside className="layout-rail" aria-label="Navigation">
          {rail}
        </aside>

        <main id="main-content" className="layout-main" aria-label="Main content">
          {main}
        </main>

        {detail && (
          <aside className="layout-detail" aria-label="Details panel">
            {detail}
          </aside>
        )}
      </div>
    </div>
  )
}

// --- Status Indicator ---

interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'checking'
  generationInProgress?: boolean
  generatingSessionId?: string | null
}

function StatusIndicator({ status, generationInProgress, generatingSessionId }: StatusIndicatorProps) {
  // Show generation status when online and generating
  if (status === 'online' && generationInProgress) {
    return (
      <div className="status-indicator status-indicator-generating" role="status">
        <span className="status-indicator-dot status-indicator-dot-pulse" />
        <span className="status-indicator-label">
          Generating{generatingSessionId ? '...' : ''}
        </span>
      </div>
    )
  }

  const labels = {
    online: 'Connected',
    offline: 'Offline',
    checking: 'Connecting...',
  }

  return (
    <div className={`status-indicator status-indicator-${status}`} role="status">
      <span className="status-indicator-dot" />
      <span className="status-indicator-label">{labels[status]}</span>
    </div>
  )
}
