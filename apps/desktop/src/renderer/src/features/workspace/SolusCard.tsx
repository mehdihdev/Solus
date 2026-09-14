// The project's `.solus` on Home (SOLUSDEV-253): what SOL knows about THIS
// project — five sections of typed notes, SOL-filed notes and imported files
// (docs/api/solus.md) — readable and editable where the project is chosen,
// not only from the Workspace nodes. Reuses the Workspace's own hook and
// actions, so a note added here is the same node the graph shows. Honest
// states: no project, offline, loading. Nothing is fabricated for an empty
// section; deletion is armed on one click and confirmed on the next.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { SOLUS_SECTIONS, type SolusEntry, type SolusSection } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import { SolusComposer } from '../graph/SolusComposer'
import {
  formatSize,
  sectionCountLabel,
  useSolusActions,
  type Composer
} from '../graph/solusActions'
import { SECTION_LABELS, useSolusConfig } from '../graph/useSolusConfig'
import './solusCard.css'

const INTRO =
  'Everything SOL knows about this project — notes, files and what SOL filed. ' +
  'Yours to read and change; SOL reads it on every turn.'
const NO_PROJECT_NOTE = 'Open or switch to a project to see its .solus.'
const OFFLINE_NOTE = "Solus can't reach its API — the project's .solus appears when it does."
const EMPTY_SECTION_NOTE = 'Nothing here yet.'
/** How long a first "Delete" click stays armed before it quietly disarms. */
export const DELETE_ARM_MS = 4000
/** A confirm inside this window after arming is a double-click or a held
 *  key, not a decision (security review M1): ignored. */
export const DELETE_DWELL_MS = 400

export interface SolusCardProps {
  projectId: string | null
  projectName: string | null
}

export function SolusCard({ projectId, projectName }: SolusCardProps): React.JSX.Element {
  const solus = useSolusConfig(projectId)
  const actions = useSolusActions(projectId, solus)
  const [open, setOpen] = useState<SolusSection | null>(null)
  const [composer, setComposer] = useState<Composer | null>(null)
  const [importTarget, setImportTarget] = useState<SolusSection | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const online = solus.status === 'ready'

  const importInto = (section: SolusSection): void => {
    setImportTarget(section)
    fileInput.current?.click()
  }
  const onFilePicked = (files: FileList | null): void => {
    const file = files?.[0]
    if (file && importTarget) void actions.importFile(importTarget, file)
    if (fileInput.current) fileInput.current.value = ''
  }
  const submit = async (text: string): Promise<void> => {
    if (composer && (await actions.submit(composer, text))) setComposer(null)
  }

  return (
    <Card pad={16} aria-label=".solus" data-testid="solus-card">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <Mono size={10}>.SOLUS</Mono>
        {projectName && (
          <Mono size={9.5} color="var(--mut)" style={{ textTransform: 'none' }}>
            {projectName}
          </Mono>
        )}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5, margin: '6px 0 10px' }}>
        {projectId === null ? NO_PROJECT_NOTE : INTRO}
      </div>
      {projectId !== null && solus.status === 'loading' && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 12 }}>
          <Spinner size={14} />
        </div>
      )}
      {projectId !== null && solus.status === 'offline' && (
        <div role="note" style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
          {OFFLINE_NOTE}
        </div>
      )}
      {projectId !== null && online && (
        <div>
          {SOLUS_SECTIONS.map((section) => (
            <SectionRow
              key={section}
              section={section}
              entries={solus.sections[section]}
              open={open === section}
              composer={composer?.section === section ? composer : null}
              onToggle={() => setOpen((current) => (current === section ? null : section))}
              onCompose={setComposer}
              onImport={() => importInto(section)}
              onRemove={actions.remove}
              onSubmit={submit}
            />
          ))}
        </div>
      )}
      <input
        ref={fileInput}
        type="file"
        hidden
        aria-label="Import a file into .solus"
        onChange={(e) => onFilePicked(e.target.files)}
      />
    </Card>
  )
}

interface SectionRowProps {
  section: SolusSection
  entries: readonly SolusEntry[]
  open: boolean
  composer: Composer | null
  onToggle: () => void
  onCompose: (next: Composer | null) => void
  onImport: () => void
  onRemove: (entry: SolusEntry) => Promise<boolean>
  onSubmit: (text: string) => Promise<void>
}

function SectionRow({
  section,
  entries,
  open,
  composer,
  onToggle,
  onCompose,
  onImport,
  onRemove,
  onSubmit
}: SectionRowProps): React.JSX.Element {
  const panelId = `solus-card-panel-${section}`
  return (
    <div>
      <SectionToggle
        section={section}
        open={open}
        onToggle={onToggle}
        panelId={panelId}
        count={entries.length}
      />
      <div className="solus-card-panel" data-open={open} id={panelId}>
        <div>
          {open && (
            <div style={{ padding: '2px 4px 12px 25px' }}>
              {entries.length === 0 && composer === null && (
                <div style={{ fontSize: 11, color: 'var(--mut)', marginBottom: 8 }}>
                  {EMPTY_SECTION_NOTE}
                </div>
              )}
              {entries.map((entry) =>
                composer?.kind === 'edit' && composer.entry?.id === entry.id ? (
                  <SolusComposer
                    key={`edit-${entry.id}`}
                    kind="edit"
                    initial={entry.text ?? ''}
                    onCancel={() => onCompose(null)}
                    onSubmit={onSubmit}
                  />
                ) : (
                  <EntryRow
                    key={entry.id}
                    entry={entry}
                    onEdit={() => onCompose({ section, kind: 'edit', entry })}
                    onRemove={() => void onRemove(entry)}
                  />
                )
              )}
              {composer?.kind === 'type' ? (
                <SolusComposer
                  kind="type"
                  initial=""
                  onCancel={() => onCompose(null)}
                  onSubmit={onSubmit}
                />
              ) : (
                <div style={{ display: 'flex', gap: 6, marginTop: entries.length ? 8 : 0 }}>
                  <Button
                    kind="ghost"
                    size="sm"
                    onClick={() => onCompose({ section, kind: 'type' })}
                  >
                    Add a note
                  </Button>
                  <Button kind="ghost" size="sm" onClick={onImport}>
                    Import file
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EntryRow({
  entry,
  onEdit,
  onRemove
}: {
  entry: SolusEntry
  onEdit: () => void
  onRemove: () => void
}): React.JSX.Element {
  const [armed, setArmed] = useState(false)
  const armedAt = useRef(0)
  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), DELETE_ARM_MS)
    return () => clearTimeout(timer)
  }, [armed])
  const isFile = entry.kind === 'artifact'
  // The concrete thing being deleted, for the button's name (security review L1).
  const subject = entry.name ?? entry.text?.slice(0, 80) ?? 'note'
  const onDeleteClick = (): void => {
    if (!armed) {
      armedAt.current = Date.now()
      setArmed(true)
      return
    }
    if (Date.now() - armedAt.current < DELETE_DWELL_MS) return
    setArmed(false)
    onRemove()
  }
  return (
    <div className="solus-card-entry" data-testid={`solus-entry-${entry.id}`}>
      {isFile ? (
        <div style={{ fontSize: 11.5, display: 'flex', gap: 8, alignItems: 'baseline' }}>
          <span style={{ color: 'var(--acc)', display: 'inline-flex' }}>
            <Icons.file size={12} />
          </span>
          <span style={{ overflowWrap: 'anywhere' }}>{entry.name}</span>
        </div>
      ) : (
        <p className="solus-card-entry-text">{entry.text}</p>
      )}
      <div className="solus-card-entry-meta">
        {isFile ? (
          <span>
            {[entry.media_type, formatSize(entry.size_bytes)].filter(Boolean).join(' · ')}
          </span>
        ) : (
          <span>{entry.author === 'sol' ? 'filed by SOL' : 'you'}</span>
        )}
        <span>{relativeTime(entry.updated_at)}</span>
        <span className="spacer" />
        {!isFile && (
          <button type="button" className="solus-card-link" onClick={onEdit}>
            Edit
          </button>
        )}
        <button
          type="button"
          className="solus-card-link"
          data-danger="true"
          data-armed={armed}
          aria-label={armed ? `Confirm delete ${subject}` : `Delete ${subject}`}
          onKeyDown={(e) => {
            if (e.repeat) e.preventDefault() // a held key is not two decisions
          }}
          onClick={onDeleteClick}
        >
          {armed ? 'Confirm delete?' : 'Delete'}
        </button>
      </div>
    </div>
  )
}

function SectionToggle({
  section,
  open,
  onToggle,
  panelId,
  count
}: Pick<SectionRowProps, 'section' | 'open' | 'onToggle'> & {
  panelId: string
  count: number
}): React.JSX.Element {
  return (
    <button
      type="button"
      className="solus-card-row"
      aria-expanded={open}
      aria-controls={panelId}
      onClick={onToggle}
    >
      <span className="solus-card-chevron">
        <Icons.arrowR size={11} />
      </span>
      <span style={{ flex: 1 }}>{SECTION_LABELS[section]}</span>
      {section === 'errors' && (
        <Mono size={8} color="var(--mut)">
          AUTO + YOU
        </Mono>
      )}
      <Mono size={9} color="var(--mut)">
        {sectionCountLabel(count)}
      </Mono>
    </button>
  )
}
