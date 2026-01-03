/**
 * App - Main Application Component
 *
 * Orchestrates the Bauhaus-styled Qwen Daemon UI:
 * - Three-panel layout with profiles rail, chat canvas, tools panel
 * - Command palette for quick actions
 * - Local-first state persistence
 */

import {
  Layout,
  ProfileRail,
  ToolsPanel,
  CommandPalette,
  ChatView,
} from './components'
import { useAppState } from './hooks'
import './App.css'

export default function App() {
  const {
    // State
    connectionStatus,
    profiles,
    selectedProfile,
    profileTools,
    currentSession,
    chatLoading,
    chatError,
    paletteOpen,
    recentCommands,
    profilesLoading,
    toolsLoading,
    commands,

    // Actions
    selectProfile,
    sendMessage,
    clearError,
    openPalette,
    closePalette,
  } = useAppState()

  return (
    <>
      <Layout
        connectionStatus={connectionStatus}
        onCommandPalette={openPalette}
        rail={
          <ProfileRail
            profiles={profiles}
            selectedProfile={selectedProfile}
            onSelectProfile={selectProfile}
            loading={profilesLoading}
          />
        }
        main={
          <ChatView
            messages={currentSession?.messages ?? []}
            onSendMessage={sendMessage}
            profileName={selectedProfile}
            loading={chatLoading}
            error={chatError}
            onClearError={clearError}
          />
        }
        detail={
          <ToolsPanel
            tools={profileTools}
            profileName={selectedProfile}
            loading={toolsLoading}
          />
        }
      />

      <CommandPalette
        isOpen={paletteOpen}
        onClose={closePalette}
        commands={commands}
        recentCommandIds={recentCommands}
        placeholder="Search commands, profiles, tools..."
      />
    </>
  )
}
