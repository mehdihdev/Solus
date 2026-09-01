// SOLUSDEV-233: the SOL page's left column — the caller's saved chats for the
// active project, newest first, with a new-chat affordance. Selection and
// "new chat" are the chat hook's transitions; this component only renders.
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { SolConversation } from './solApi'
import { useSolConversations } from './useSolConversations'

const UNTITLED = 'New chat'

function ChatRow({
  conversation,
  active,
  onSelect
}: {
  conversation: SolConversation
  active: boolean
  onSelect: (id: string) => void
}): React.JSX.Element {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-current={active ? 'true' : undefined}
      onClick={() => onSelect(conversation.id)}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(conversation.id)}
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
  const { conversations, status } = useSolConversations(projectId, activeConversationId)
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
          />
        ))}
      </div>
    </div>
  )
}
