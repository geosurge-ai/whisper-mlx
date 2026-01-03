/**
 * ProfileRail - Left sidebar for profile selection
 *
 * Displays available profiles with Bauhaus-inspired color coding.
 */

import type { ProfileInfo } from '../api'
import './ProfileRail.css'

interface ProfileRailProps {
  profiles: ProfileInfo[]
  selectedProfile: string
  onSelectProfile: (name: string) => void
  loading?: boolean
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
  loading,
}: ProfileRailProps) {
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

      <div className="profile-rail-footer">
        <p className="profile-rail-hint">
          Press <kbd>⌘K</kbd> then type profile name
        </p>
      </div>
    </nav>
  )
}
