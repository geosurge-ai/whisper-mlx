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
    generationInProgress,
    generatingSessionId,
    queuedSessionIds,
    profiles,
    selectedProfile,
    profileTools,
    sessions,
    currentSession,
    chatLoading,
    chatError,
    activity,
    paletteOpen,
    recentCommands,
    profilesLoading,
    toolsLoading,
    sessionsLoading,
    commands,

    // Actions
    selectProfile,
    sendMessage,
    clearError,
    clearActivityLog,
    openPalette,
    closePalette,
    newSession,
    switchSession,
  } = useAppState()

  return (
    <>
      <Layout
        connectionStatus={connectionStatus}
        generationInProgress={generationInProgress}
        generatingSessionId={generatingSessionId}
        onCommandPalette={openPalette}
        rail={
          <ProfileRail
            profiles={profiles}
            selectedProfile={selectedProfile}
            onSelectProfile={selectProfile}
            sessions={sessions}
            currentSessionId={currentSession?.id ?? null}
            onSwitchSession={switchSession}
            onNewSession={newSession}
            generatingSessionId={generatingSessionId}
            queuedSessionIds={queuedSessionIds}
            loading={profilesLoading}
            sessionsLoading={sessionsLoading}
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
            activity={activity}
            onClearActivityLog={clearActivityLog}
            currentSessionId={currentSession?.id ?? null}
            generatingSessionId={generatingSessionId}
            generatingSessionTitle={
              sessions.find(s => s.id === generatingSessionId)?.title ?? null
            }
            onGoToGeneratingSession={() => {
              if (generatingSessionId) switchSession(generatingSessionId)
            }}
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
