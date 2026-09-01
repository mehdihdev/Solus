// SOL screen (SOLUSDEV-233 redesign): three columns — the caller's saved chats,
// the chat column (the same OrbChat surface the orb panel uses, driven by ONE
// shared chat instance), and the CONTEXT IN USE / SOL USAGE panel. The header
// keeps SOL's visual identity, the universal Guide/Expert mode (ADR-016, now
// persisted to the server so the next turn's prompt actually follows it), and
// a grounded line driven by the project's REAL connected-source count
// (SOLUSDEV-152 charter: never a fabricated number).
import { useEffect, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { SolOrb } from '../../components/ui/SolOrb'
import { getProject, updateSolMode } from '../../lib/api/resources'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { ChatsSidebar } from './ChatsSidebar'
import { ContextPanel } from './ContextPanel'
import { OrbChat } from './OrbChat'
import { UsagePanel } from './UsagePanel'
import { selectOrbPulse, useOrbStore } from './orbStore'
import { useSolChat } from './useSolChat'

/** The project's real connected-source count, or null while unknown/offline. */
function useGroundedSources(projectId: string | null): number | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    setCount(null)
    if (!projectId || !fetchEnabled) return
    let stale = false
    getProject(projectId)
      .then((detail) => {
        if (!stale) setCount(detail.sources.length)
      })
      .catch(() => undefined)
    return () => {
      stale = true
    }
  }, [projectId, fetchEnabled])
  return count
}

export function SolScreen(): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const projectId = project?.id ?? null
  const chat = useSolChat(projectId)
  const sourceCount = useGroundedSources(projectId)

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ChatsSidebar
        projectId={projectId}
        activeConversationId={chat.activeConversationId}
        onSelect={chat.selectConversation}
        onNewChat={chat.startNewChat}
      />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <SolHeader projectName={project?.name ?? null} sourceCount={sourceCount} />
        <OrbChat projectId={projectId} layout="page" chat={chat} />
      </div>
      <div
        style={{
          width: 288,
          flexShrink: 0,
          borderLeft: '1px solid var(--bd)',
          overflowY: 'auto',
          padding: '14px 16px 24px'
        }}
      >
        <ContextPanel contextUsed={chat.contextUsed} />
        <UsagePanel creditsExhausted={chat.creditsExhausted} />
      </div>
    </div>
  )
}

function SolHeader({
  projectName,
  sourceCount
}: {
  projectName: string | null
  sourceCount: number | null
}): React.JSX.Element {
  const pulse = useOrbStore(selectOrbPulse)
  const solMode = useSettingsStore((s) => s.solMode)
  const changeMode = (mode: SolMode): void => {
    const previous = useSettingsStore.getState().solMode
    useSettingsStore.getState().setSolMode(mode)
    // ADR-016: the server's stored mode is what the next turn's prompt reads —
    // persist, and revert the optimistic flip if the PATCH fails.
    updateSolMode(mode).catch(() => useSettingsStore.getState().setSolMode(previous))
  }
  const grounded =
    sourceCount !== null && sourceCount > 0
      ? ` · GROUNDED IN ${sourceCount} CONNECTION${sourceCount === 1 ? '' : 'S'}`
      : ''
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '16px 24px 10px',
        maxWidth: 800,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box'
      }}
    >
      <SolOrb size={48} pulse={pulse} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
        <Mono size={9.5} color="var(--mut)">
          {projectName ?? 'NO PROJECT'}
          {grounded}
        </Mono>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Segmented
          options={['Guide', 'Expert']}
          value={solMode}
          onChange={changeMode}
          ariaLabel="SOL mode"
        />
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 5 }}>
          {solMode === 'Guide' ? 'explains and teaches' : 'terse, direct'}
        </div>
      </div>
    </div>
  )
}
