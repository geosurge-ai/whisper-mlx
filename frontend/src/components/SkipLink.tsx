/**
 * SkipLink - Accessibility skip navigation link
 *
 * Allows keyboard users to skip to main content.
 */

import './SkipLink.css'

export function SkipLink() {
  return (
    <a href="#main-content" className="skip-link">
      Skip to main content
    </a>
  )
}
