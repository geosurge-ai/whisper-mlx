/**
 * ToolsPanel - Right sidebar showing available tools
 *
 * Displays tools for the selected profile with expandable descriptions.
 */

import { useState } from 'react'
import type { ToolInfo } from '../api'
import './ToolsPanel.css'

interface ToolsPanelProps {
  tools: ToolInfo[]
  profileName: string
  onInvokeTool?: (toolName: string) => void
  loading?: boolean
}

export function ToolsPanel({
  tools,
  profileName,
  onInvokeTool,
  loading,
}: ToolsPanelProps) {
  const [expandedTool, setExpandedTool] = useState<string | null>(null)

  if (loading) {
    return (
      <div className="tools-panel">
        <div className="tools-panel-header">
          <h2 className="tools-panel-title">Tools</h2>
        </div>
        <div className="tools-panel-loading">
          <span>Loading...</span>
        </div>
      </div>
    )
  }

  if (tools.length === 0) {
    return (
      <div className="tools-panel">
        <div className="tools-panel-header">
          <h2 className="tools-panel-title">Tools</h2>
          <span className="tools-panel-profile">{profileName}</span>
        </div>
        <div className="tools-panel-empty">
          <p>No tools available for this profile.</p>
          <p className="tools-panel-empty-hint">
            Switch to <strong>mirror</strong> or <strong>code_runner</strong> for tool access.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="tools-panel">
      <div className="tools-panel-header">
        <h2 className="tools-panel-title">Tools</h2>
        <span className="tools-panel-count">{tools.length}</span>
      </div>

      <ul className="tools-list">
        {tools.map((tool) => (
          <li key={tool.name}>
            <div
              className={`tool-item ${expandedTool === tool.name ? 'tool-item-expanded' : ''}`}
            >
              <button
                className="tool-item-header"
                onClick={() => setExpandedTool(
                  expandedTool === tool.name ? null : tool.name
                )}
                aria-expanded={expandedTool === tool.name}
              >
                <span className="tool-item-name">{tool.name}</span>
                <span className="tool-item-chevron">
                  {expandedTool === tool.name ? '−' : '+'}
                </span>
              </button>

              {expandedTool === tool.name && (
                <div className="tool-item-body">
                  <p className="tool-item-description">{tool.description}</p>

                  {onInvokeTool && (
                    <button
                      className="tool-item-invoke"
                      onClick={() => onInvokeTool(tool.name)}
                    >
                      Invoke Tool
                    </button>
                  )}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
