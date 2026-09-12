// SOL screen (SOLUSDEV-233 redesign): three columns — the caller's saved chats,
// the chat column (the same SolChat surface the SOL window uses, driven by ONE
// shared chat instance), and the CONTEXT IN USE / SOL USAGE panel. The header
// keeps the SOL wordmark, the window opener, and
// a grounded line driven by the project's REAL connected-source count
// (SOLUSDEV-152 charter: never a fabricated number).
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { getProject } from '../../lib/api/resources'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { ChatsSidebar } from './ChatsSidebar'
import { ContextPanel } from './ContextPanel'
import { SolChat } from './SolChat'
import { UsagePanel } from './UsagePanel'
import { useSolChat } from './useSolChat'

/** The project's real connected-source count, or null while unknown/offline.
 *  Keyed by project and derived, so a switch reads null until ITS count lands. */
function useGroundedSources(projectId: string | null): number | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [loaded, setLoaded] = useState<{ projectId: string; count: number } | null>(null)
  useEffect(() => {
    if (!projectId || !fetchEnabled) return
    let stale = false
    getProject(projectId)
      .then((detail) => {
        if (!stale) setLoaded({ projectId, count: detail.sources.length })
      })
      .catch(() => undefined)
    return () => {
      stale = true
    }
  }, [projectId, fetchEnabled])
  return fetchEnabled && loaded?.projectId === projectId ? loaded.count : null
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
        <SolChat projectId={projectId} layout="page" chat={chat} />
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
  // SOLUSDEV-252 S3 (wireflow §F): the summon-free way into the SOL window —
  // the path that still works where hotkeys cannot (Wayland). Electron only.
  const solBridge = getDesktopSolBridge()
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
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
        <Mono size={9.5} color="var(--mut)">
          {projectName ?? 'NO PROJECT'}
          {grounded}
        </Mono>
      </div>
      {solBridge && (
        <Button kind="ghost" size="sm" onClick={() => void solBridge.open()}>
          Open SOL window
        </Button>
      )}
    </div>
  )
}
