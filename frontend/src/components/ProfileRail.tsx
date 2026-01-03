/**
 * ProfileRail - Left sidebar for profile and session navigation
 *
 * Displays available profiles and sessions with Bauhaus-inspired color coding.
 */

import type { ProfileInfo, SessionSummary } from '../api'
import './ProfileRail.css'

interface ProfileRailProps {
  profiles: ProfileInfo[]
  selectedProfile: string
  onSelectProfile: (name: string) => void
  sessions: SessionSummary[]
  currentSessionId: string | null
  onSwitchSession: (sessionId: string) => void
  onNewSession: () => void
  generatingSessionId?: string | null
  queuedSessionIds?: string[]
  loading?: boolean
  sessionsLoading?: boolean
}

// Bauhaus color mapping for profiles
const PROFILE_COLORS: Record<string, string> = {
  general: 'var(--color-secondary)',   // Blue
  mirror: 'var(--color-primary)',      // Red
  code_runner: 'var(--color-accent)',  // Yellow/Orange
}

export function ProfileRail({
  profiles,
  selectedProfile,
  onSelectProfile,
  sessions,
  currentSessionId,
  onSwitchSession,
  onNewSession,
  generatingSessionId,
  queuedSessionIds = [],
  loading,
  sessionsLoading,
}: ProfileRailProps) {
  // Filter sessions for current profile
  const profileSessions = sessions.filter(s => s.profile_name === selectedProfile)

  if (loading) {
    return (
      <div className="profile-rail">
        <div className="profile-rail-header">
          <h2 className="profile-rail-title">Profiles</h2>
        </div>
        <div className="profile-rail-loading">
          <span>Loading...</span>
        </div>
      </div>
    )
  }

  return (
    <nav className="profile-rail">
      {/* Profiles Section */}
      <div className="profile-rail-header">
        <h2 className="profile-rail-title">Profiles</h2>
      </div>

      <ul className="profile-list" role="listbox" aria-label="Select profile">
        {profiles.map((profile) => (
          <li key={profile.name}>
            <button
              className={`profile-item ${selectedProfile === profile.name ? 'profile-item-selected' : ''}`}
              onClick={() => onSelectProfile(profile.name)}
              role="option"
              aria-selected={selectedProfile === profile.name}
              style={{
                '--profile-color': PROFILE_COLORS[profile.name] ?? 'var(--color-text-tertiary)',
              } as React.CSSProperties}
            >
              <span className="profile-item-indicator" />
              <div className="profile-item-content">
                <span className="profile-item-name">{profile.name}</span>
                <span className="profile-item-tools">
                  {profile.tool_names.length === 0
                    ? 'No tools'
                    : `${profile.tool_names.length} tools`}
                </span>
              </div>
            </button>
          </li>
        ))}
      </ul>

      {/* Sessions Section */}
      <div className="profile-rail-sessions">
        <div className="profile-rail-sessions-header">
          <h3 className="profile-rail-sessions-title">Sessions</h3>
          <button
            className="profile-rail-new-session"
            onClick={onNewSession}
            aria-label="New session"
          >
            +
          </button>
        </div>

        {sessionsLoading ? (
          <div className="profile-rail-loading">
            <span>Loading...</span>
          </div>
        ) : profileSessions.length === 0 ? (
          <div className="profile-rail-empty">
            <span>No sessions yet</span>
          </div>
        ) : (
          <ul className="session-list" role="listbox" aria-label="Select session">
            {profileSessions.map((session) => {
              const isGenerating = generatingSessionId === session.id
              const isQueued = queuedSessionIds.includes(session.id)
              const isCurrent = currentSessionId === session.id

              return (
                <li key={session.id}>
                  <button
                    className={`session-item ${isCurrent ? 'session-item-selected' : ''} ${isGenerating ? 'session-item-generating' : ''} ${isQueued ? 'session-item-queued' : ''}`}
                    onClick={() => onSwitchSession(session.id)}
                    role="option"
                    aria-selected={isCurrent}
                  >
                    <div className="session-item-content">
                      <span className="session-item-title">
                        {session.title ?? 'Untitled session'}
                      </span>
                      <span className="session-item-meta">
                        {session.message_count} messages
                        {isGenerating && ' • Generating...'}
                        {isQueued && ' • Queued'}
                      </span>
                    </div>
                    {isGenerating && (
                      <span className="session-item-status session-item-status-generating" />
                    )}
                    {isQueued && !isGenerating && (
                      <span className="session-item-status session-item-status-queued" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="profile-rail-footer">
        <p className="profile-rail-hint">
          Press <kbd>⌘K</kbd> for quick actions
        </p>
      </div>
    </nav>
  )
}
