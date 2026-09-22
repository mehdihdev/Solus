import { useCallback, useEffect, useRef, useState } from 'react'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { useServiceCatalog } from './useServiceCatalog'
import { useServiceAttachments, type SelectService } from './useServiceAttachments'
import { ServiceAccountPanel } from './ServiceAccountPanel'

interface WorkspaceAddProps {
  projectId: string | null
  onSelected: SelectService
  hardware?: React.ReactNode
  /** A sequence-keyed request (like the navigator's `reveal`) to open the panel on a tab. */
  openRequest?: { tab: 'service' | 'hardware'; sequence: number }
}
export function WorkspaceAdd({
  projectId,
  onSelected,
  hardware,
  openRequest
}: WorkspaceAddProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const [tab, setTab] = useState<'service' | 'hardware'>('service')
  const [expanded, setExpanded] = useState<string | null>(null)
  const anchor = useRef<HTMLDivElement>(null)
  const enabled = useWorkspaceFetchEnabled() && projectId !== null
  const { catalog, state } = useServiceCatalog(open && enabled)
  const project = useServiceAttachments(projectId, onSelected)
  useEffect(() => {
    if (open && enabled) void project.session.load()
  }, [open, enabled, project.session])
  useAddDismiss(open, anchor, close)
  // Keyed by sequence, not object identity: a re-render never re-opens a closed panel.
  const requestedTab = openRequest?.tab
  const requestSequence = openRequest?.sequence
  useEffect(() => {
    if (requestSequence === undefined || !requestedTab) return
    setTab(requestedTab)
    setOpen(true)
  }, [requestSequence, requestedTab])
  return (
    <div className="workspace-add" ref={anchor}>
      <button type="button" aria-expanded={open} disabled={!enabled} onClick={() => setOpen(!open)}>
        Add
      </button>
      {open && (
        <div role="dialog" aria-label="Add to workspace" className="workspace-add-panel">
          <header>
            <strong>Add to workspace</strong>
            <button type="button" aria-label="Close Add" onClick={() => setOpen(false)}>
              ×
            </button>
          </header>
          <div role="tablist" aria-label="Add type">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'service'}
              onClick={() => setTab('service')}
            >
              Integrations
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'hardware'}
              onClick={() => setTab('hardware')}
            >
              Hardware
            </button>
          </div>
          {tab === 'hardware' ? (
            (hardware ?? <p>No hardware added.</p>)
          ) : (
            <ServiceAccountPanel
              catalog={catalog}
              state={state}
              project={project}
              expanded={expanded}
              onExpand={(id) => {
                setExpanded(expanded === id ? null : id)
                if (!state.accounts.find((account) => account.id === id)?.document_tree) {
                  void catalog.loadDocuments(id)
                }
              }}
            />
          )}
          {project.state.busyId && <p role="status">Importing document…</p>}
          {project.state.error && <p role="alert">{project.state.error}</p>}
        </div>
      )}
    </div>
  )
}

function useAddDismiss(
  open: boolean,
  anchor: React.RefObject<HTMLDivElement | null>,
  close: () => void
): void {
  useEffect(() => {
    if (!open) return
    const key = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        close()
      }
    }
    const outside = (event: PointerEvent): void => {
      if (event.target instanceof Node && !anchor.current?.contains(event.target)) close()
    }
    document.addEventListener('keydown', key, true)
    document.addEventListener('pointerdown', outside)
    return () => {
      document.removeEventListener('keydown', key, true)
      document.removeEventListener('pointerdown', outside)
    }
  }, [open, anchor, close])
}
