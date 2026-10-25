// The SOL page's left column (design template): a "New chat ⌘N" card, the caller's saved
// chats for the active project grouped by last activity (TODAY / THIS WEEK / EARLIER),
// each with its title and relative time — never a fabricated message count — and the
// usage card at the bottom. Selection and "new chat" are the chat hook's transitions;
// rename/delete round-trip the owner-private endpoints and a deleted chat's ~/.solus
// cache file goes with it. The list itself is lifted to SolScreen (the header shows it).
import { useEffect, useState, type ReactNode } from 'react'
import { clampMenuPosition } from '../../components/ui/ContextMenu'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { relativeTime } from '../../lib/relativeTime'
import { isModKeyShortcut, modKeyHint } from '../palette/paletteHotkey'
import { DeleteConfirmModal, NameModal } from '../workspace/modals'
import { groupChats } from './chatGroups'
import { isMac } from './commandHotkey'
import { removeCachedChat } from './solCache'
import { deleteSolConversation, renameSolConversation, type SolConversation } from './solApi'
import type { SolConversationsData } from './useSolConversations'

export const UNTITLED = 'New chat'

//: Approximate rendered menu box, used to clamp the context menu inside the
//: viewport (a row near the bottom edge must not push Delete off-screen).
const MENU_BOX = { width: 150, height: 90 }

/** Right-click menu state: which chat, and where the pointer was. */
interface MenuState {
  conversation: SolConversation
  x: number
  y: number
}

function ChatMenu({
  menu,
  onClose,
  onRename,
  onDelete
}: {
  menu: MenuState
  onClose: () => void
  onRename: () => void
  onDelete: () => void
}): React.JSX.Element {
  const itemStyle: React.CSSProperties = {
    display: 'block',
    width: '100%',
    textAlign: 'left',
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    fontFamily: 'var(--font-ui)',
    fontSize: 12.5,
    padding: '9px 12px'
  }
  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={onClose} />
      <div
        role="menu"
        className="popover-in"
        style={{
          position: 'fixed',
          left: menu.x,
          top: menu.y,
          zIndex: 61,
          minWidth: 140,
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 4,
          boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
          overflow: 'hidden'
        }}
      >
        <button
          type="button"
          role="menuitem"
          className="interactive"
          onClick={onRename}
          style={{ ...itemStyle, color: 'var(--tx)' }}
        >
          Rename
        </button>
        <button
          type="button"
          role="menuitem"
          className="interactive"
          onClick={onDelete}
          style={{ ...itemStyle, color: 'var(--err)' }}
        >
          Delete
        </button>
      </div>
    </>
  )
}

function ChatRow({
  conversation,
  active,
  onSelect,
  onMenu
}: {
  conversation: SolConversation
  active: boolean
  onSelect: (id: string) => void
  onMenu: (state: MenuState) => void
}): React.JSX.Element {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-current={active ? 'true' : undefined}
      onClick={() => onSelect(conversation.id)}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(conversation.id)}
      onContextMenu={(e) => {
        e.preventDefault()
        onMenu({ conversation, ...clampMenuPosition(e.clientX, e.clientY, MENU_BOX) })
      }}
      className="interactive sol-row-in sol-chat-row"
      data-active={active || undefined}
    >
      <div className="sol-chat-row-title">{conversation.title?.trim() || UNTITLED}</div>
      <Mono size={10}>{relativeTime(conversation.updated_at || conversation.created_at)}</Mono>
    </div>
  )
}

function ChatList({
  projectId,
  data,
  activeConversationId,
  onSelect,
  onMenu
}: {
  projectId: string | null
  data: SolConversationsData
  activeConversationId: string | null
  onSelect: (conversationId: string) => void
  onMenu: (state: MenuState) => void
}): React.JSX.Element {
  const { conversations, status } = data
  return (
    <div className="sol-chat-list">
      {status === 'loading' && conversations.length === 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 14 }}>
          <Spinner size={14} />
        </div>
      )}
      {status === 'offline' && <p className="sol-side-empty">Chats unavailable — offline.</p>}
      {status === 'ready' && conversations.length === 0 && (
        <p className="sol-side-empty">
          {projectId
            ? 'No chats yet. Ask SOL anything to start one.'
            : 'Open a project to see its chats.'}
        </p>
      )}
      {groupChats(conversations).map((group) => (
        <div key={group.label} className="sol-chat-group">
          <Mono size={10} ls="0.08em" className="sol-chat-group-label">
            {group.label}
          </Mono>
          {group.items.map((c) => (
            <ChatRow
              key={c.id}
              conversation={c}
              active={c.id === activeConversationId}
              onSelect={onSelect}
              onMenu={onMenu}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

/** The rename/delete flows the context menu opens (SOLUSDEV-233). */
function ChatActions({
  projectId,
  activeConversationId,
  onNewChat,
  onDone,
  renaming,
  deleting,
  close
}: {
  projectId: string
  activeConversationId: string | null
  onNewChat: () => void
  onDone: () => void
  renaming: SolConversation | null
  deleting: SolConversation | null
  close: () => void
}): React.JSX.Element | null {
  if (renaming) {
    return (
      <NameModal
        title="Rename chat"
        label="Chat name"
        submitLabel="Save"
        initial={renaming.title?.trim() || UNTITLED}
        maxLength={512}
        errorText="Couldn't rename the chat. Please try again."
        onClose={close}
        onSubmit={async (name) => {
          try {
            await renameSolConversation(projectId, renaming.id, name)
            onDone()
            return true
          } catch {
            return false
          }
        }}
      />
    )
  }
  if (deleting) {
    return (
      <DeleteConfirmModal
        name={deleting.title?.trim() || UNTITLED}
        noun="chat"
        detail="and its messages"
        onClose={close}
        onConfirm={async () => {
          try {
            await deleteSolConversation(projectId, deleting.id)
            removeCachedChat(projectId, deleting.id)
            // Deleting the open chat clears the transcript to a fresh one.
            if (deleting.id === activeConversationId) onNewChat()
            onDone()
            return true
          } catch {
            return false
          }
        }}
      />
    )
  }
  return null
}

/** ⌘N / Ctrl+N starts a new chat while the SOL page is mounted (the hint on the card is
 *  only shown because the chord really works). */
function useNewChatHotkey(onNewChat: () => void): void {
  useEffect(() => {
    const mac = isMac()
    const onKey = (event: KeyboardEvent): void => {
      if (!isModKeyShortcut(event, mac, 'n')) return
      event.preventDefault()
      onNewChat()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onNewChat])
}

export function ChatsSidebar({
  projectId,
  activeConversationId,
  data,
  onSelect,
  onNewChat,
  footer
}: {
  projectId: string | null
  activeConversationId: string | null
  data: SolConversationsData
  onSelect: (conversationId: string) => void
  onNewChat: () => void
  /** The usage card, rendered last. */
  footer?: ReactNode
}): React.JSX.Element {
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [renaming, setRenaming] = useState<SolConversation | null>(null)
  const [deleting, setDeleting] = useState<SolConversation | null>(null)
  useNewChatHotkey(onNewChat)
  return (
    <div className="sol-chats">
      <div style={{ padding: 12 }}>
        <button
          type="button"
          aria-label="New chat"
          className="interactive sol-new-chat"
          onClick={onNewChat}
        >
          <span>New chat</span>
          <Mono size={10} style={{ textTransform: 'none' }}>
            {modKeyHint(isMac(), 'n')}
          </Mono>
        </button>
      </div>
      <ChatList
        projectId={projectId}
        data={data}
        activeConversationId={activeConversationId}
        onSelect={onSelect}
        onMenu={setMenu}
      />
      {footer}
      {menu && (
        <ChatMenu
          menu={menu}
          onClose={() => setMenu(null)}
          onRename={() => {
            setRenaming(menu.conversation)
            setMenu(null)
          }}
          onDelete={() => {
            setDeleting(menu.conversation)
            setMenu(null)
          }}
        />
      )}
      {projectId && (
        <ChatActions
          projectId={projectId}
          activeConversationId={activeConversationId}
          onNewChat={onNewChat}
          onDone={data.refresh}
          renaming={renaming}
          deleting={deleting}
          close={() => {
            setRenaming(null)
            setDeleting(null)
          }}
        />
      )}
    </div>
  )
}
