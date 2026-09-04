// SOLUSDEV-235 / EXT-15 — the `+ Add widget` picker (wireflow "Picker").
// Three sections: built-ins, installed extensions with a widget view, and a
// developer section only while a dev registration list is passed. Requirement
// hints follow store.md's rules; an unknown sources list means UNMET, never met.
import { useEffect } from 'react'
import type { SourceKind, WidgetSizeHint, WidgetSlotSize } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { missingRequirements, requirementLabel } from '../extensions/extensionLogic'
import { ModalShell } from '../workspace/modals'
import type { BuiltinWidgetEntry, ExtensionWidgetEntry } from './useAvailableWidgets'

/** A developer-mode registration with a widget view (session-only, Settings → Developer). */
export interface DevWidgetEntry {
  readonly ref: string
  readonly name: string
  /** The unpacked folder, shown as the row's hint. */
  readonly path: string
  readonly size: WidgetSizeHint
}

export interface AddWidgetPickerProps {
  readonly builtins: readonly BuiltinWidgetEntry[]
  readonly extensions: readonly ExtensionWidgetEntry[]
  readonly dev?: readonly DevWidgetEntry[]
  /** Refs already on the canvas — one slot per widget. */
  readonly onCanvas: ReadonlySet<string>
  /** The project's connected source kinds; undefined/null = unknown = every requirement unmet. */
  readonly connectedKinds?: ReadonlySet<SourceKind> | null
  readonly onAdd: (ref: string, size: WidgetSlotSize) => void
  readonly onClose: () => void
  readonly onOpenStore?: () => void
}

export const PICKER_WIDTH = 560
export const NO_EXTENSION_WIDGETS = 'No installed extensions add widgets yet — browse the Store'

type RowState =
  | { readonly kind: 'add' }
  | { readonly kind: 'added' }
  | { readonly kind: 'unmet'; readonly label: string; readonly mono: boolean }

function extensionRowState(
  entry: ExtensionWidgetEntry,
  onCanvas: ReadonlySet<string>,
  connected: ReadonlySet<SourceKind> | null
): RowState {
  if (entry.blocked) return { kind: 'unmet', label: 'blocked by your team', mono: false }
  if (!entry.enabled) return { kind: 'unmet', label: 'disabled in this project', mono: false }
  const missing = missingRequirements(entry.requires, connected ?? new Set())
  if (missing.length > 0)
    return { kind: 'unmet', label: `NEEDS ${requirementLabel(missing)}`, mono: true }
  return onCanvas.has(entry.ref) ? { kind: 'added' } : { kind: 'add' }
}

function PickerRow(props: {
  title: string
  hint: React.ReactNode
  badge?: React.ReactNode
  state: RowState
  onAdd: () => void
}): React.JSX.Element {
  const { title, hint, badge, state, onAdd } = props
  return (
    <div
      role="listitem"
      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', minWidth: 0 }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--tx)', flex: 'none' }}>
        {title}
      </span>
      {badge}
      <span
        style={{
          fontSize: 11.5,
          color: 'var(--mut)',
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
      >
        {state.kind === 'unmet' && !state.mono ? state.label : hint}
      </span>
      {state.kind === 'add' && (
        <Button kind="ghost" size="sm" onClick={onAdd} aria-label={`Add ${title}`}>
          Add
        </Button>
      )}
      {state.kind === 'added' && <Mono size={9.5}>Added</Mono>}
      {state.kind === 'unmet' && state.mono && <Mono size={9.5}>{state.label}</Mono>}
    </div>
  )
}

function Section({
  title,
  children
}: {
  title: string
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <section aria-label={title} style={{ marginTop: 16 }}>
      <Mono size={9.5}>{title}</Mono>
      <div role="list">{children}</div>
    </section>
  )
}

function domainsHint(entry: BuiltinWidgetEntry): string {
  return entry.domains.length === 0 ? 'All domains' : entry.domains.join(' · ')
}

function useEscape(onClose: () => void): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
}

export function AddWidgetPicker(props: AddWidgetPickerProps): React.JSX.Element {
  const { builtins, extensions, dev = [], onCanvas, connectedKinds, onAdd, onClose } = props
  useEscape(onClose)
  const add = (ref: string, size: WidgetSizeHint): void => {
    onAdd(ref, size.preferred)
    onClose()
  }
  const addedOr = (ref: string): RowState =>
    onCanvas.has(ref) ? { kind: 'added' } : { kind: 'add' }

  return (
    <ModalShell onClose={onClose} width={PICKER_WIDTH}>
      <div role="dialog" aria-label="Add widget" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Mono size={10.5} color="var(--tx)">
            Add widget
          </Mono>
          <Button kind="bare" size="sm" onClick={onClose} aria-label="Close">
            <Icons.x size={12} />
          </Button>
        </div>

        <Section title="Built-in">
          {builtins.map((b) => (
            <PickerRow
              key={b.ref}
              title={b.title}
              hint={domainsHint(b)}
              state={addedOr(b.ref)}
              onAdd={() => add(b.ref, b.size)}
            />
          ))}
        </Section>

        <Section title="Installed extensions">
          {extensions.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0' }}>
              <span style={{ fontSize: 12, color: 'var(--mut)', flex: 1 }}>
                {NO_EXTENSION_WIDGETS}
              </span>
              {props.onOpenStore && (
                <Button kind="ghost" size="sm" onClick={props.onOpenStore}>
                  Browse the Store
                </Button>
              )}
            </div>
          ) : (
            extensions.map((e) => (
              <PickerRow
                key={e.ref}
                title={e.name}
                hint={e.summary}
                badge={
                  e.verified ? <Icons.verified size={12} title="Verified publisher" /> : undefined
                }
                state={extensionRowState(e, onCanvas, connectedKinds ?? null)}
                onAdd={() => add(e.ref, e.size)}
              />
            ))
          )}
        </Section>

        {dev.length > 0 && (
          <Section title="Developer (this session)">
            {dev.map((d) => (
              <PickerRow
                key={d.ref}
                title={d.name}
                badge={<Mono size={9}>Dev</Mono>}
                hint={<span className="font-mono">{d.path}</span>}
                state={addedOr(d.ref)}
                onAdd={() => add(d.ref, d.size)}
              />
            ))}
          </Section>
        )}
      </div>
    </ModalShell>
  )
}
