// SOLUSDEV-327 — the SOL sidebar docked to the right of the current shell screen
// (wireflow sol-sidebar.md). It drives the SAME per-project chat session as the SOL page and the
// pill (`useSolChat`), so moving between surfaces never starts a new chat. Hidden on the SOL page.
import { useCallback, useEffect, useRef } from 'react'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useSolusConfig } from '../../graph/useSolusConfig'
import { selectFocusedEntity, useFocusStore } from '../../workspace/focusStore'
import type { MainScreen, ShellRoute } from '../../workspace/shellStore'
import { pageAnchors } from '../pageAnchors'
import { selectPins, usePinnedContextStore } from '../pinnedContextStore'
import { SolChat } from '../SolChat'
import { openCitation } from '../SolScreen'
import { SOL_SEND_MODE } from '../solWindowStore'
import { useSolChat } from '../useSolChat'
import { useSolConversations } from '../useSolConversations'
import { ChatSwitcher } from './ChatSwitcher'
import { closeSidebar, toggleSidebar } from './sidebarActions'
import { sidebarCopy } from './sidebarCopy'
import type { SidebarTrigger } from './sidebarEvents'
import { useSidebarHotkey } from './sidebarHotkey'
import { useSidebarPresence, useSidebarResize, useWindowFit } from './sidebarHooks'
import { SIDEBAR_EXPAND_MS, SIDEBAR_POP_MS } from './sidebarMotion.constants'
import { ResizeHandle, SidebarGreeting, SidebarHeader } from './SidebarParts'
import { selectSidebarOpen, sidebarKey, useSolSidebarStore } from './solSidebarStore'
import './solSidebar.css'

export const SOL_SIDEBAR_TOGGLE_ID = 'sol-sidebar-toggle'

export interface SolSidebarHostProps {
  route: ShellRoute
  navigate: (screen: MainScreen) => void
}

export function SolSidebarHost({ route, navigate }: SolSidebarHostProps): React.JSX.Element | null {
  const key = sidebarKey(route)
  const onSolPage = key === 'sol'
  const open = useSolSidebarStore((s) => selectSidebarOpen(s, key))
  const presence = useSidebarPresence(open, key)
  const toggleFromShortcut = useCallback(() => {
    if (!toggleSidebar(key, 'shortcut')) returnFocusToToggle()
  }, [key])
  useSidebarHotkey(toggleFromShortcut, !onSolPage)
  if (onSolPage || presence.phase === 'closed') return null
  return <SolSidebarPanel screen={key} presence={presence} navigate={navigate} />
}

/** Closing hands focus back to the control that opens it again. */
function returnFocusToToggle(): void {
  document.getElementById(SOL_SIDEBAR_TOGGLE_ID)?.focus()
}

function SolSidebarPanel({
  screen,
  presence,
  navigate
}: {
  screen: string
  presence: ReturnType<typeof useSidebarPresence>
  navigate: (screen: MainScreen) => void
}): React.JSX.Element {
  const ref = useRef<HTMLElement>(null)
  const fit = useWindowFit(screen)
  const resize = useSidebarResize()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  // SOLUSDEV-326: on Hardware every turn parks a card, and cards stay in the page's slot.
  const onHardware = screen === 'hardware'
  const chat = useSolChat(projectId, onHardware ? 'hardware' : undefined)
  const solus = useSolusConfig(projectId)
  const pins = usePinnedContextStore((s) => selectPins(s, projectId, chat.activeConversationId))
  const focusedName = useFocusStore((s) => selectFocusedEntity(s)?.name ?? null)
  const copy = sidebarCopy(screen, focusedName)
  const pinIds = pins.map((pin) => pin.id)
  const ask = useChipSend(projectId, chat, pinIds)
  const { expand, popOut } = useSidebarExits(presence, screen, navigate)
  useFocusComposerOnOpen(ref, presence.phase)

  const close = (via: SidebarTrigger): void => {
    closeSidebar(screen, via)
    returnFocusToToggle()
  }

  return (
    <aside
      ref={ref}
      aria-label="SOL sidebar"
      className="sol-sb"
      data-phase={presence.phase}
      data-fit={fit}
      style={{ ['--sb-w' as string]: `${resize.width}px` }}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.defaultPrevented) close('escape')
      }}
    >
      <ResizeHandle resize={resize} />
      <div className="sol-sb-inner">
        <SidebarHeader
          tag={copy.tag}
          working={chat.streaming}
          onPopOut={popOut}
          onExpand={expand}
          onClose={() => close('header')}
        />
        {projectId && <SidebarChatSwitcher projectId={projectId} chat={chat} onShowAll={expand} />}
        <SolChat
          projectId={projectId}
          layout="sidebar"
          chat={chat}
          pinnedMentionIds={pinIds}
          placeholder={copy.placeholder}
          cardsInSlot={onHardware}
          onAddNodeFromGraph={() => navigate('workspace')}
          onFocusEntity={(target) => openCitation(target, solus.sections, navigate)}
          emptyState={
            <SidebarGreeting greeting={copy.greeting} suggestions={copy.suggestions} onAsk={ask} />
          }
        />
      </div>
    </aside>
  )
}

/** The two ways the panel leaves for another SOL surface: morph into the SOL page, or shrink
 *  into the pill (Electron only — undefined where there is no SOL window bridge). */
function useSidebarExits(
  presence: ReturnType<typeof useSidebarPresence>,
  screen: string,
  navigate: (screen: MainScreen) => void
): { expand: () => void; popOut: (() => void) | undefined } {
  const solBridge = getDesktopSolBridge()
  const expand = (): void =>
    presence.exit('expanding', SIDEBAR_EXPAND_MS, () => {
      navigate('sol')
      closeSidebar(screen, 'header', 'expand')
    })
  const popOut = solBridge
    ? (): void =>
        presence.exit('popping', SIDEBAR_POP_MS, () => {
          closeSidebar(screen, 'header', 'pop_out')
          void solBridge.open()
        })
    : undefined
  return { expand, popOut }
}

/** The chat switcher on the shared session: picking or starting a chat moves every SOL surface. */
function SidebarChatSwitcher({
  projectId,
  chat,
  onShowAll
}: {
  projectId: string
  chat: ReturnType<typeof useSolChat>
  onShowAll: () => void
}): React.JSX.Element {
  const conversations = useSolConversations(projectId, chat.activeConversationId)
  return (
    <ChatSwitcher
      data={conversations}
      activeConversationId={chat.activeConversationId}
      onSelect={chat.selectConversation}
      onNewChat={chat.startNewChat}
      onShowAll={onShowAll}
    />
  )
}

/** A suggestion chip is the person's message: sent like a typed one from the sidebar (Build,
 *  auto-routed, the page's anchors). */
function useChipSend(
  projectId: string | null,
  chat: ReturnType<typeof useSolChat>,
  pinIds: readonly string[]
): (text: string) => void {
  return (text) => {
    // A click racing a project switch: never pair this project's chat with the next one's focus.
    if (useWorkspaceStore.getState().project?.id !== projectId) return
    void chat.send(text, SOL_SEND_MODE, [], false, undefined, pageAnchors(pinIds))
  }
}

/** Opening moves focus into the composer, once the panel has settled open. */
function useFocusComposerOnOpen(
  ref: React.RefObject<HTMLElement | null>,
  phase: ReturnType<typeof useSidebarPresence>['phase']
): void {
  const previous = useRef(phase)
  useEffect(() => {
    if (previous.current === 'entering' && phase === 'open') {
      ref.current?.querySelector<HTMLTextAreaElement>('textarea')?.focus({ preventScroll: true })
    }
    previous.current = phase
  }, [phase, ref])
}
