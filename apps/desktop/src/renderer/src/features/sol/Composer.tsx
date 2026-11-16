// The SOL composer: the message box with its `@` picker and Send. Moved out of SolChat.tsx
// (SOLUSDEV-319) so the pill variant has room to grow. SOLUSDEV-327: no mode badge, Think harder,
// Confirm every change or routing line on any surface — SOL builds, routes and asks for
// confirmation as needed (every send is Build, auto-routed, no forced confirmation).
import { useLayoutEffect, useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { takeDraft } from './pinnedContextStore'
import { COMPOSER_ATTR } from './commandHotkey'
import { useSolSessionStore } from './solSessionStore'
import type { Entity } from '../../lib/api/resources'
import { useMentionPicker, type MentionPicker } from './useMentionPicker'

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

const COMPOSER_MAX_HEIGHT = 160

/** Grow with the draft up to a ceiling (jsdom reports no scrollHeight, so this is a no-op there). */
function useAutosize(ref: MentionPicker['inputRef'], value: string): void {
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    if (el.scrollHeight) el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_HEIGHT)}px`
  }, [ref, value])
}

/** The message box plus its `@` picker. Split from Composer so each stays
 *  readable — the composer owns text/mode/send, this owns the input element. */
function MessageInput({
  mention,
  inputRef,
  value,
  onChange,
  onSubmitRequest,
  page,
  placeholder,
  pill = false
}: {
  mention: MentionPicker
  // Passed beside the picker, not read off it: a ref read during render taints
  // the whole object for the react-hooks/refs rule.
  inputRef: MentionPicker['inputRef']
  value: string
  onChange: (text: string) => void
  /** Enter (no Shift, no Ctrl/Cmd — those belong to the command cards) sends. */
  onSubmitRequest: () => void
  page: boolean
  placeholder: string
  /** SOLUSDEV-319: the borderless input inside the Ember Pill bar. */
  pill?: boolean
}): React.JSX.Element {
  useAutosize(inputRef, value)
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
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement | null>}
        rows={1}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          mention.onInput(e.target)
        }}
        onKeyDown={(e) => {
          if (mention.onKeyDown(e)) return
          if (
            e.key === 'Enter' &&
            !e.shiftKey &&
            !e.ctrlKey &&
            !e.metaKey &&
            !e.nativeEvent.isComposing
          ) {
            e.preventDefault()
            onSubmitRequest()
          }
        }}
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
        className={pill ? 'sol-pill-input' : undefined}
        style={pill ? undefined : INPUT_STYLE}
      />
    </>
  )
}

const INPUT_STYLE: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  minHeight: 20,
  resize: 'none',
  background: 'transparent',
  border: 0,
  color: 'var(--tx)',
  fontFamily: 'var(--font-ui)',
  fontSize: 13,
  lineHeight: 1.5,
  padding: '6px 4px',
  outline: 'none'
}

/** The design's "+" beside the composer: upload a file or image into .solus, or go pick a
 *  node from the graph. Rendered only when the surface offers those paths (the page). */
function AttachMenu({
  onUpload,
  onAddNodeFromGraph
}: {
  onUpload?: (file: File) => void
  onAddNodeFromGraph?: () => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const file = useRef<HTMLInputElement | null>(null)
  return (
    <div style={{ position: 'relative', flex: 'none' }}>
      <button
        type="button"
        aria-label="Attach"
        aria-haspopup="menu"
        aria-expanded={open}
        className="interactive"
        onClick={() => setOpen((on) => !on)}
        style={{
          width: 32,
          height: 32,
          borderRadius: 4,
          background: 'var(--sur2)',
          border: '1px solid var(--bd)',
          color: 'var(--tx)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer'
        }}
      >
        <Icons.plus size={15} />
      </button>
      <input
        ref={file}
        type="file"
        aria-label="Upload file or image"
        style={{ display: 'none' }}
        onChange={(event) => {
          const picked = event.currentTarget.files?.[0]
          event.currentTarget.value = ''
          if (picked) onUpload?.(picked)
        }}
      />
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 20 }} onClick={() => setOpen(false)} />
          <div role="menu" className="popover-in sol-attach-menu">
            {onUpload && (
              <button
                type="button"
                role="menuitem"
                className="interactive"
                onClick={() => {
                  setOpen(false)
                  file.current?.click()
                }}
              >
                Upload file or image
              </button>
            )}
            {onAddNodeFromGraph && (
              <button
                type="button"
                role="menuitem"
                className="interactive"
                onClick={() => {
                  setOpen(false)
                  onAddNodeFromGraph()
                }}
              >
                Add node from graph
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** The composer placeholder: the region, when attached, is the subject. */
const PLACEHOLDER = 'Ask about a signal, a change, a part…'
const PAGE_PLACEHOLDER = 'Ask SOL about this project…'
const PLACEHOLDER_WITH_REGION = 'What would you like to know about it?'
/** SOLUSDEV-319: the pill acts in the tool in front, not just answers. */
const PILL_PLACEHOLDER = 'Ask SOL, or tell it what to do…'

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

export type ComposerSend = (text: string, mentions: readonly string[]) => void

export function Composer({
  streaming,
  page,
  projectId,
  regionAttached,
  onDismissRegion,
  onSend,
  pill = false,
  footerStart,
  footerEnd,
  onUpload,
  onAddNodeFromGraph,
  placeholder
}: ComposerProps): React.JSX.Element {
  // The page may arrive with a hand-off draft ("Ask SOL" from the Workspace).
  const [input, setInput] = useState(() => (page ? (takeDraft() ?? '') : ''))
  const empty = input.trim() === ''

  // All the `@`-picker state lives in its own hook — see useMentionPicker.
  const mention = useMentionPicker(projectId, input, setInput)

  const submit = (): void => {
    const text = input.trim()
    if (!text || streaming) return
    onSend(text, mention.mentionIds)
    setInput('')
    mention.reset()
  }
  const form: FormState = {
    mention,
    input,
    setInput,
    submit,
    streaming,
    empty,
    regionAttached,
    onDismissRegion
  }
  return pill ? (
    <PillForm {...form} footerStart={footerStart} footerEnd={footerEnd} />
  ) : (
    <ColumnForm
      {...form}
      page={page}
      onUpload={onUpload}
      onAddNodeFromGraph={onAddNodeFromGraph}
      placeholder={placeholder}
    />
  )
}

/** What both composer layouts render from: one state, one send path. */
interface FormState {
  mention: MentionPicker
  input: string
  setInput: (text: string) => void
  submit: () => void
  streaming: boolean
  empty: boolean
  regionAttached: boolean
  onDismissRegion: () => void
}

/** The panel / page / sidebar composer: the boxed input with + and Send. */
function ColumnForm({
  mention,
  input,
  setInput,
  submit,
  streaming,
  empty,
  regionAttached,
  onDismissRegion,
  page,
  onUpload,
  onAddNodeFromGraph,
  placeholder
}: FormState & {
  page: boolean
  onUpload?: (file: File) => void
  onAddNodeFromGraph?: () => void
  placeholder?: string
}): React.JSX.Element {
  const attach = Boolean(onUpload || onAddNodeFromGraph)

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      style={{
        padding: page ? '12px 20px 18px' : 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        ...(page ? { width: '100%', boxSizing: 'border-box' } : {})
      }}
    >
      {regionAttached && <RegionChip onDismiss={onDismissRegion} />}
      <div className="sol-composer-box">
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', position: 'relative' }}>
          {attach && <AttachMenu onUpload={onUpload} onAddNodeFromGraph={onAddNodeFromGraph} />}
          <MessageInput
            mention={mention}
            inputRef={mention.inputRef}
            value={input}
            onChange={setInput}
            onSubmitRequest={submit}
            page={page}
            placeholder={
              regionAttached
                ? PLACEHOLDER_WITH_REGION
                : (placeholder ?? (page ? PAGE_PLACEHOLDER : PLACEHOLDER))
            }
          />
          <SendButton streaming={streaming} empty={empty} />
        </div>
      </div>
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
        height: 32,
        flex: 'none',
        background: 'var(--acc)',
        color: 'var(--acc-ink)',
        border: 'none',
        borderRadius: 4,
        padding: '0 14px',
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
  regionAttached: boolean
  onDismissRegion: () => void
  onSend: ComposerSend
  /** SOLUSDEV-319: render as the Ember Pill bar + footer. */
  pill?: boolean
  /** Pill footer, leading (SOL, sees-screen) and trailing (hide) slots. */
  footerStart?: React.ReactNode
  footerEnd?: React.ReactNode
  /** Page: the attach menu's two paths. Absent ⇒ no "+" button. */
  onUpload?: (file: File) => void
  onAddNodeFromGraph?: () => void
  /** SOLUSDEV-327: the sidebar's per-screen placeholder (column layouts only). */
  placeholder?: string
}


interface PillFormProps extends FormState {
  footerStart?: React.ReactNode
  footerEnd?: React.ReactNode
}

/** SOLUSDEV-319: the Ember Pill bar (orb · input · send) and its
 *  footer. Same state and send path as the panel composer — only the layout differs. */
function PillForm(p: PillFormProps): React.JSX.Element {
  // The shared streaming flag (every SOL surface) — the old window header's signal.
  const pulsing = useSolSessionStore((s) => s.streaming)
  return (
    <form
      className="sol-pill-bar"
      onSubmit={(e) => {
        e.preventDefault()
        p.submit()
      }}
    >
      <div className="sol-pill-row">
        <span className={pulsing ? 'sol-pill-orb sol-pulse' : 'sol-pill-orb'} aria-hidden />
        <MessageInput
          mention={p.mention}
          inputRef={p.mention.inputRef}
          value={p.input}
          onChange={p.setInput}
          onSubmitRequest={p.submit}
          page={false}
          pill
          placeholder={p.regionAttached ? PLACEHOLDER_WITH_REGION : PILL_PLACEHOLDER}
        />
        <button
          type="submit"
          className="sol-pill-send"
          aria-label="Send"
          disabled={p.streaming || p.empty}
        >
          <svg aria-hidden width="16" height="16" viewBox="0 0 16 16">
            <path
              d="M8 13V3M3.5 7.5 8 3l4.5 4.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
      <div className="sol-pill-footer">
        {p.footerStart}
        {p.regionAttached && <RegionChip onDismiss={p.onDismissRegion} />}
        <span style={{ flex: 1 }} />
        {p.footerEnd}
      </div>
    </form>
  )
}
