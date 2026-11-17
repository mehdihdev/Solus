// A user-role turn in the SOL thread (split from SolChat.tsx): the person's own message as their
// bubble, and (SOLUSDEV-326) the two turns Solus writes for them as quiet lines that cannot pass
// for typed words: a device notice on SOL's side in the thread's system-line style (the tool
// row's), and an answered question as a right-aligned receipt naming the button. One rendering
// each, live and reloaded. All text nodes: an answer's label is model-written.
import { answerReceipt } from './solChatItems'
import type { ChatItem } from './solChatStore'

const LINE: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--mut)'
}

interface UserRowProps {
  item: ChatItem
  rowClass: string
  page: boolean
}

export function UserRow({ item, rowClass, page }: UserRowProps): React.JSX.Element {
  if (item.kind === 'notice') {
    return (
      <div data-testid="sol-notice-line" className={rowClass} style={LINE}>
        {item.content}
      </div>
    )
  }
  if (item.kind === 'answer') {
    return (
      <div
        data-testid="sol-answer-line"
        className={rowClass}
        style={{ ...LINE, alignSelf: 'flex-end', textAlign: 'right', whiteSpace: 'pre-wrap' }}
      >
        {answerReceipt(item.content)}
      </div>
    )
  }
  return (
    <div className={rowClass} style={{ alignSelf: 'flex-end', maxWidth: page ? '78%' : '85%' }}>
      <div
        data-testid="sol-user-bubble"
        style={{
          background: 'var(--sur2)',
          border: '1px solid var(--bd)',
          borderRadius: 6,
          padding: page ? '10px 13px' : '8px 10px',
          fontSize: 12.5,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap'
        }}
      >
        {item.content}
      </div>
      {/* SOLUSDEV-252 S3: a flag, never the pixels (sol-window.md §8). */}
      {item.hasScreenshot && (
        <div style={{ fontSize: 10, color: 'var(--mut)', textAlign: 'right', marginTop: 3 }}>
          screen attached
        </div>
      )}
    </div>
  )
}
