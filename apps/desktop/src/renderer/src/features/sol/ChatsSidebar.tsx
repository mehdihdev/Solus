// SOLUSDEV-233: the SOL page's left column — the caller's saved chats for the
// active project, newest first, with a new-chat affordance and a right-click
// menu (rename / delete). Selection and "new chat" are the chat hook's
// transitions; rename/delete round-trip the owner-private endpoints and a
// deleted chat's ~/.solus cache file goes with it.
import { useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import { DeleteConfirmModal, NameModal } from '../workspace/modals'
import { removeCachedChat } from './solCache'
import { deleteSolConversation, renameSolConversation, type SolConversation } from './solApi'
import { useSolConversations } from './useSolConversations'

const UNTITLED = 'New chat'

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
        onMenu({ conversation, x: e.clientX, y: e.clientY })
      }}
      className="interactive sol-row-in"
      style={{
        padding: '10px 12px',
        borderRadius: 5,
        cursor: 'pointer',
        background: active ? 'var(--sur2)' : 'transparent',
        border: `1px solid ${active ? 'var(--bd)' : 'transparent'}`
      }}
    >
      <div
        style={{
          fontSize: 12.5,
          fontWeight: 600,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
      >
        {conversation.title?.trim() || UNTITLED}
      </div>
      <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
        {relativeTime(conversation.created_at)}
      </div>
    </div>
  )
}

function ChatList({
  projectId,
  conversations,
  status,
  activeConversationId,
  onSelect,
  onMenu
}: {
  projectId: string | null
  conversations: readonly SolConversation[]
  status: 'loading' | 'ready' | 'offline'
  activeConversationId: string | null
  onSelect: (conversationId: string) => void
  onMenu: (state: MenuState) => void
}): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: '0 8px 12px'
      }}
    >
      {status === 'loading' && conversations.length === 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 14 }}>
          <Spinner size={14} />
        </div>
      )}
      {status === 'offline' && (
        <div style={{ fontSize: 11, color: 'var(--mut)', padding: '6px 6px' }}>
          Chats unavailable — offline.
        </div>
      )}
      {status === 'ready' && conversations.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--mut)', padding: '6px 6px', lineHeight: 1.5 }}>
          {projectId
            ? 'No chats yet. Ask SOL anything to start one.'
            : 'Open a project to see its chats.'}
        </div>
      )}
      {conversations.map((c) => (
        <ChatRow
          key={c.id}
          conversation={c}
          active={c.id === activeConversationId}
          onSelect={onSelect}
          onMenu={onMenu}
        />
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

export function ChatsSidebar({
  projectId,
  activeConversationId,
  onSelect,
  onNewChat
}: {
  projectId: string | null
  activeConversationId: string | null
  onSelect: (conversationId: string) => void
  onNewChat: () => void
}): React.JSX.Element {
  const { conversations, status, refresh } = useSolConversations(projectId, activeConversationId)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [renaming, setRenaming] = useState<SolConversation | null>(null)
  const [deleting, setDeleting] = useState<SolConversation | null>(null)
  return (
    <div
      style={{
        width: 224,
        flexShrink: 0,
        borderRight: '1px solid var(--bd)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0
      }}
    >
      <div
        style={{
          padding: '14px 14px 10px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>CHATS</Mono>
        <button
          type="button"
          aria-label="New chat"
          className="interactive"
          onClick={onNewChat}
          style={{
            background: 'transparent',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            color: 'var(--tx)',
            cursor: 'pointer',
            padding: '3px 6px',
            display: 'inline-flex'
          }}
        >
          <Icons.plus size={12} />
        </button>
      </div>
      <ChatList
        projectId={projectId}
        conversations={conversations}
        status={status}
        activeConversationId={activeConversationId}
        onSelect={onSelect}
        onMenu={setMenu}
      />
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
          onDone={refresh}
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
