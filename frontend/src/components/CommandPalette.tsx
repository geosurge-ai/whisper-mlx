/**
 * CommandPalette - Global ⌘K command palette
 *
 * Features:
 * - Fuzzy search across actions, profiles, tools
 * - Keyboard navigation (↑↓ to select, Enter to execute, Esc to close)
 * - Recent commands history
 * - Bauhaus-inspired modal design
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useFocusTrap } from '../hooks'
import './CommandPalette.css'

// --- Types ---

export type CommandType = 'action' | 'profile' | 'tool' | 'recent'

export interface Command {
  id: string
  type: CommandType
  label: string
  description?: string
  shortcut?: string
  onExecute: () => void
}

interface CommandPaletteProps {
  isOpen: boolean
  onClose: () => void
  commands: Command[]
  recentCommandIds?: string[]
  placeholder?: string
}

// --- Fuzzy Search ---

function fuzzyMatch(query: string, text: string): boolean {
  const lowerQuery = query.toLowerCase()
  const lowerText = text.toLowerCase()

  // Simple contains match
  if (lowerText.includes(lowerQuery)) return true

  // Character-by-character fuzzy match
  let queryIndex = 0
  for (let i = 0; i < lowerText.length && queryIndex < lowerQuery.length; i++) {
    if (lowerText[i] === lowerQuery[queryIndex]) {
      queryIndex++
    }
  }
  return queryIndex === lowerQuery.length
}

function scoreMatch(query: string, text: string): number {
  const lowerQuery = query.toLowerCase()
  const lowerText = text.toLowerCase()

  // Exact match gets highest score
  if (lowerText === lowerQuery) return 100

  // Starts with gets high score
  if (lowerText.startsWith(lowerQuery)) return 80

  // Contains gets medium score
  if (lowerText.includes(lowerQuery)) return 60

  // Fuzzy match gets low score
  return 40
}

// --- Component ---

export function CommandPalette({
  isOpen,
  onClose,
  commands,
  recentCommandIds = [],
  placeholder = 'Type a command or search...',
}: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const focusTrapRef = useFocusTrap(isOpen)

  // Filter and sort commands
  const filteredCommands = useMemo(() => {
    if (!query.trim()) {
      // Show recent commands first, then actions
      const recent = recentCommandIds
        .map(id => commands.find(c => c.id === id))
        .filter((c): c is Command => c !== undefined)
        .map(c => ({ ...c, type: 'recent' as CommandType }))

      const others = commands
        .filter(c => !recentCommandIds.includes(c.id))
        .slice(0, 10)

      return [...recent.slice(0, 5), ...others]
    }

    return commands
      .filter(cmd =>
        fuzzyMatch(query, cmd.label) ||
        (cmd.description && fuzzyMatch(query, cmd.description))
      )
      .sort((a, b) => {
        const scoreA = scoreMatch(query, a.label)
        const scoreB = scoreMatch(query, b.label)
        return scoreB - scoreA
      })
      .slice(0, 15)
  }, [query, commands, recentCommandIds])

  // Reset state when opened
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      // Focus input after a tick (for animation)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && filteredCommands.length > 0) {
      const selectedItem = listRef.current.children[selectedIndex] as HTMLElement | undefined
      selectedItem?.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex, filteredCommands.length])

  // Keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, filteredCommands.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
        break
      case 'Enter':
        e.preventDefault()
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].onExecute()
          onClose()
        }
        break
      case 'Escape':
        e.preventDefault()
        onClose()
        break
    }
  }, [filteredCommands, selectedIndex, onClose])

  // Global keyboard shortcut
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        if (isOpen) {
          onClose()
        }
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const typeLabels: Record<CommandType, string> = {
    action: 'Action',
    profile: 'Profile',
    tool: 'Tool',
    recent: 'Recent',
  }

  return (
    <div className="command-palette-overlay" onClick={onClose}>
      <div
        ref={focusTrapRef}
        className="command-palette"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        {/* Search Input */}
        <div className="command-palette-input-wrapper">
          <input
            ref={inputRef}
            type="text"
            className="command-palette-input"
            placeholder={placeholder}
            value={query}
            onChange={e => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
            aria-label="Search commands"
            aria-activedescendant={
              filteredCommands[selectedIndex]
                ? `command-${filteredCommands[selectedIndex].id}`
                : undefined
            }
          />
          <kbd className="command-palette-esc">ESC</kbd>
        </div>

        {/* Results List */}
        <ul
          ref={listRef}
          className="command-palette-list"
          role="listbox"
        >
          {filteredCommands.length === 0 ? (
            <li className="command-palette-empty">
              No commands found for "{query}"
            </li>
          ) : (
            filteredCommands.map((cmd, index) => (
              <li
                key={cmd.id}
                id={`command-${cmd.id}`}
                className={`command-palette-item ${index === selectedIndex ? 'command-palette-item-selected' : ''}`}
                onClick={() => {
                  cmd.onExecute()
                  onClose()
                }}
                onMouseEnter={() => setSelectedIndex(index)}
                role="option"
                aria-selected={index === selectedIndex}
              >
                <span className={`command-palette-type command-palette-type-${cmd.type}`}>
                  {typeLabels[cmd.type]}
                </span>
                <div className="command-palette-item-content">
                  <span className="command-palette-item-label">{cmd.label}</span>
                  {cmd.description && (
                    <span className="command-palette-item-description">
                      {cmd.description}
                    </span>
                  )}
                </div>
                {cmd.shortcut && (
                  <kbd className="command-palette-shortcut">{cmd.shortcut}</kbd>
                )}
              </li>
            ))
          )}
        </ul>

        {/* Footer */}
        <div className="command-palette-footer">
          <span><kbd>↑↓</kbd> Navigate</span>
          <span><kbd>↵</kbd> Select</span>
          <span><kbd>ESC</kbd> Close</span>
        </div>
      </div>
    </div>
  )
}
