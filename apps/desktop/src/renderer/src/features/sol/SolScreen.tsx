// SOL page (design template): three columns — the caller's saved chats (grouped, with
// the usage card at the bottom), the chat column (the active chat's title, the pinned
// count, the SOL window opener, the thread and the composer), and the context column
// (instructions · files · pinned nodes · artifacts · last-turn manifest). ONE shared chat
// instance drives all three. Nothing here invents a number: the header count is the
// chat's pinned nodes, and the files are the project's real .solus entries.
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolusActions } from '../graph/solusActions'
import { useSolusConfig } from '../graph/useSolusConfig'
import { useFocusStore } from '../workspace/focusStore'
import type { MainScreen } from '../workspace/shellStore'
import { ChatsSidebar, UNTITLED } from './ChatsSidebar'
import { chatKey, selectPins, usePinnedContextStore } from './pinnedContextStore'
import { SolChat } from './SolChat'
import { SolRightPanel } from './SolRightPanel'
import { UsagePanel } from './UsagePanel'
import { useSolChat } from './useSolChat'
import { useSolConversations } from './useSolConversations'

export function SolScreen({
  onNavigate
}: {
  onNavigate: (screen: MainScreen) => void
}): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const projectId = project?.id ?? null
  const chat = useSolChat(projectId)
  const conversations = useSolConversations(projectId, chat.activeConversationId)
  const solus = useSolusConfig(projectId)
  const actions = useSolusActions(projectId, solus)
  const pins = usePinnedContextStore((s) => selectPins(s, projectId, chat.activeConversationId))
  // The first send created the conversation: pins made on the fresh chat follow it.
  const active = chat.activeConversationId
  useEffect(() => {
    if (projectId && active) usePinnedContextStore.getState().adoptConversation(projectId, active)
  }, [projectId, active])
  const unpin = (entityId: string): void => {
    if (projectId) usePinnedContextStore.getState().unpin(chatKey(projectId, active), entityId)
  }
  const upload = (file: File): void => {
    void actions.importFile('documentation', file)
  }
  const title = conversations.conversations.find((c) => c.id === active)?.title?.trim() || UNTITLED

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ChatsSidebar
        projectId={projectId}
        activeConversationId={active}
        data={conversations}
        onSelect={chat.selectConversation}
        onNewChat={chat.startNewChat}
        footer={<UsagePanel creditsExhausted={chat.creditsExhausted} />}
      />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <SolHeader title={title} pinned={pins.length} />
        <SolChat
          projectId={projectId}
          layout="page"
          chat={chat}
          pinnedMentionIds={pins.map((pin) => pin.id)}
          onUpload={projectId ? upload : undefined}
          onAddNodeFromGraph={() => onNavigate('workspace')}
          onFocusEntity={(entityId) => {
            void useFocusStore.getState().focus(entityId)
            onNavigate('workspace')
          }}
        />
      </div>
      {projectId && (
        <SolRightPanel
          projectId={projectId}
          chat={chat}
          solus={solus}
          pins={pins}
          onUnpin={unpin}
          onUpload={upload}
          onNavigate={onNavigate}
        />
      )}
    </div>
  )
}

function SolHeader({ title, pinned }: { title: string; pinned: number }): React.JSX.Element {
  // SOLUSDEV-252 S3 (wireflow §F): the summon-free way into the SOL window —
  // the path that still works where hotkeys cannot (Wayland). Electron only.
  const solBridge = getDesktopSolBridge()
  return (
    <div className="sol-page-head">
      <span className="sol-page-title">{title}</span>
      <Mono size={10} ls="0.08em">
        {pinned} NODE{pinned === 1 ? '' : 'S'} IN CONTEXT
      </Mono>
      <div style={{ flex: 1 }} />
      {solBridge && (
        <Button kind="ghost" size="sm" onClick={() => void solBridge.open()}>
          Open SOL window
        </Button>
      )}
    </div>
  )
}
