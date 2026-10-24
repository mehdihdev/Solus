// The SOL composer: the message box with its `@` picker, the mode badge,
// Think harder, the review preference and the routing preview. Moved out of
// SolChat.tsx (SOLUSDEV-319) so the pill variant has room to grow.
import { useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Switch } from '../../components/ui/Switch'
import { ClassifyIndicator } from './ClassifyIndicator'
import { COMPOSER_ATTR } from './commandHotkey'
import { ModeBadge } from './ModeBadge'
import type { Entity } from '../../lib/api/resources'
import { useClassifyPreview } from './useClassifyPreview'
import { useMentionPicker, type MentionPicker } from './useMentionPicker'
import type { SolActionMode } from './solApi'

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

/** The `@`-mention picker. A plain listbox — the design system has no combobox,
 *  and one short list does not justify a dependency. */
function MentionList({
  results,
  activeId,
  onChoose,
  page
}: {
  results: readonly Entity[]
  activeId: string | null
  onChoose: (entity: Entity) => void
  page: boolean
}): React.JSX.Element {
  return (
    <ul
      id="sol-mention-list"
      role="listbox"
      aria-label="Graph entities"
      style={{
        position: 'absolute',
        bottom: 'calc(100% + 6px)',
        left: 0,
        right: page ? 'auto' : 0,
        minWidth: 240,
        maxHeight: 210,
        overflowY: 'auto',
        margin: 0,
        padding: 4,
        listStyle: 'none',
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 6,
        boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
        zIndex: 20
      }}
    >
      {results.map((entity) => (
        <li
          key={entity.id}
          id={`sol-mention-${entity.id}`}
          role="option"
          aria-selected={entity.id === activeId}
          // A list item is not focusable, so the input keeps focus and the
          // caret stays where the user was typing.
          onMouseDown={(e) => {
            e.preventDefault()
            onChoose(entity)
          }}
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 8,
            padding: '5px 8px',
            borderRadius: 4,
            cursor: 'pointer',
            background: entity.id === activeId ? 'var(--sur2)' : 'transparent'
          }}
        >
          <span style={{ fontSize: 12.5, color: 'var(--tx)' }}>{entity.name}</span>
          <Mono size={9.5}>{entity.type}</Mono>
          {(entity.type === 'code_file' || entity.type === 'code_module') && (
            <Mono size={9.5}>
              {typeof entity.properties?.path === 'string'
                ? entity.properties.path
                : entity.source_key}
            </Mono>
          )}
        </li>
      ))}
    </ul>
  )
}

/** The message box plus its `@` picker. Split from Composer so each stays
 *  readable — the composer owns text/mode/send, this owns the input element. */
function MessageInput({
  mention,
  inputRef,
  value,
  onChange,
  page,
  placeholder
}: {
  mention: MentionPicker
  // Passed beside the picker, not read off it: a ref read during render taints
  // the whole object for the react-hooks/refs rule.
  inputRef: MentionPicker['inputRef']
  value: string
  onChange: (text: string) => void
  page: boolean
  placeholder: string
}): React.JSX.Element {
  return (
    <>
      {mention.listOpen && (
        <MentionList
          results={mention.results}
          activeId={mention.active?.id ?? null}
          onChoose={mention.choose}
          page={page}
        />
      )}
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          mention.onInput(e.target)
        }}
        onKeyDown={(e) => void mention.onKeyDown(e)}
        onKeyUp={(e) => mention.onCaretMove(e.currentTarget)}
        onClick={(e) => mention.onCaretMove(e.currentTarget)}
        role="combobox"
        aria-expanded={mention.listOpen}
        aria-controls="sol-mention-list"
        aria-autocomplete="list"
        aria-activedescendant={mention.active ? `sol-mention-${mention.active.id}` : undefined}
        placeholder={placeholder}
        aria-label="Message SOL"
        {...{ [COMPOSER_ATTR]: '' }}
        style={{
          flex: 1,
          minWidth: 0,
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 4,
          color: 'var(--tx)',
          fontFamily: 'var(--font-ui)',
          fontSize: 12.5,
          padding: '8px 10px',
          outline: 'none'
        }}
      />
    </>
  )
}

/** The composer placeholder: the region, when attached, is the subject. */
const PLACEHOLDER = 'Ask about a signal, a change, a part…'
const PLACEHOLDER_WITH_REGION = 'What would you like to know about it?'

/** The attached-region chip on the composer (wireflow §C); × drops the pixels. */
function RegionChip({ onDismiss }: { onDismiss: () => void }): React.JSX.Element {
  return (
    <span className="sol-region-chip">
      screen
      <button type="button" aria-label="Remove screenshot" onClick={onDismiss}>
        ×
      </button>
    </span>
  )
}

function ReviewPreference({
  checked,
  onChange,
  streaming
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  streaming: boolean
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', ...MUTED }}>
      <Switch
        checked={checked}
        onChange={onChange}
        ariaLabel="Confirm every change"
        disabled={streaming}
      />
      <span>
        Confirm every change
        <span style={{ display: 'block', fontSize: 10 }}>
          Choose before sending. Review each proposed change before SOL applies it.
        </span>
      </span>
    </div>
  )
}

export type ComposerSend = (text: string, mentions: readonly string[], thinkHarder: boolean) => void

export function Composer({
  streaming,
  page,
  projectId,
  mode,
  onModeChange,
  regionAttached,
  onDismissRegion,
  forceConfirmation,
  onForceConfirmationChange,
  onSend
}: ComposerProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const classify = useClassifyPreview(input)
  const empty = input.trim() === ''

  // All the `@`-picker state lives in its own hook — see useMentionPicker.
  const mention = useMentionPicker(projectId, input, setInput)

  const submit = (): void => {
    const text = input.trim()
    if (!text || streaming) return
    onSend(text, mention.mentionIds, classify.override.thinkHarder)
    setInput('')
    mention.reset()
    classify.resetOverride() // also drops "Think harder" — it is per message
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      style={{
        borderTop: '1px solid var(--bd)',
        padding: page ? '10px 24px 14px' : 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 6
      }}
    >
      {regionAttached && <RegionChip onDismiss={onDismissRegion} />}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', position: 'relative' }}>
        <MessageInput
          mention={mention}
          inputRef={mention.inputRef}
          value={input}
          onChange={setInput}
          page={page}
          placeholder={regionAttached ? PLACEHOLDER_WITH_REGION : PLACEHOLDER}
        />
        {/* SOLUSDEV-252 S3: the SHARED action mode (main's setting under
            Electron) — the same badge the SOL window header shows. */}
        <ModeBadge mode={mode} onChange={onModeChange} />
        {/* S1-W3: one tier up for THIS message. Lives in the classify override
            state so the routing preview reflects it and the post-send reset
            clears it — one source, two controls (this and the popover). */}
        <Switch
          checked={classify.override.thinkHarder}
          onChange={(thinkHarder) => classify.setOverride({ thinkHarder })}
          ariaLabel="Think harder"
        />
        <SendButton streaming={streaming} empty={empty} />
      </div>
      <ReviewPreference
        checked={forceConfirmation}
        onChange={onForceConfirmationChange}
        streaming={streaming}
      />
      <ClassifyIndicator
        preview={classify.preview}
        override={classify.override}
        onOverride={classify.setOverride}
        onReset={classify.resetOverride}
      />
    </form>
  )
}

function SendButton({
  streaming,
  empty
}: {
  streaming: boolean
  empty: boolean
}): React.JSX.Element {
  return (
    <button
      type="submit"
      disabled={streaming || empty}
      style={{
        background: 'var(--acc)',
        color: 'var(--acc-ink)',
        border: 'none',
        borderRadius: 4,
        padding: '7px 14px',
        fontSize: 12,
        fontWeight: 600,
        cursor: streaming ? 'wait' : 'pointer',
        opacity: streaming || empty ? 0.6 : 1
      }}
    >
      Send
    </button>
  )
}

export interface ComposerProps {
  streaming: boolean
  page: boolean
  projectId: string | null
  mode: SolActionMode
  onModeChange: (mode: SolActionMode) => void
  regionAttached: boolean
  onDismissRegion: () => void
  forceConfirmation: boolean
  onForceConfirmationChange: (checked: boolean) => void
  onSend: ComposerSend
}
