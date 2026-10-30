// Add (design template): an accent button in the toolbar that opens a centred two-column
// modal — INTEGRATIONS rows on the left, the chosen source's pane on the right, and a footer
// that names the target and confirms the picked documents in order through the existing
// attach/sync path. Nothing here calls a provider: listings are the cached catalog.
import { useCallback, useEffect, useState } from 'react'
import { Icons } from '../../components/ui/icons.constants'
import type { Connection, SelectableItem } from '../../lib/api/resources'
import { countOf } from '../onboarding/pickerModel'
import { ModalShell } from '../workspace/modals'
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { AddDocumentsPane } from './AddDocumentsPane'
import { AddSourceRows, accountUsable, type AddTarget } from './AddSourceRows'
import type { CatalogSnapshot, ServiceCatalog } from './serviceCatalog'
import { SolusUploadPane } from './SolusUploadPane'
import { useServiceCatalog } from './useServiceCatalog'
import { useServiceAttachments, type SelectService } from './useServiceAttachments'

export interface SolusUpload {
  /** The section label uploads land in (the selected .solus node's, else Documentation). */
  target: string
  choose: () => void
  importFiles: (files: File[]) => Promise<void>
}

interface WorkspaceAddProps {
  projectId: string | null
  onSelected: SelectService
  hardware?: React.ReactNode
  /** A sequence-keyed request (like the navigator's `reveal`) to open the panel on a tab. */
  openRequest?: { tab: 'service' | 'hardware'; sequence: number }
  solusUpload?: SolusUpload
}

/** "The first usable account" until the user picks one; resolved against the live catalog. */
const FIRST_ACCOUNT: AddTarget = { kind: 'account', id: '' }

function resolveAccount(target: AddTarget, accounts: readonly Connection[]): Connection | null {
  if (target.kind !== 'account') return null
  if (target.id) return accounts.find((candidate) => candidate.id === target.id) ?? null
  return accounts.find(accountUsable) ?? null
}

function accountName(account: Connection): string {
  return account.account_login ?? account.provider
}

function targetName(target: AddTarget, account: Connection | null, solusTarget: string): string {
  if (target.kind === 'hardware') return 'this project'
  if (target.kind === 'solus') return `.solus › ${solusTarget}`
  return account ? accountName(account) : 'an account'
}

interface AddModel {
  open: boolean
  setOpen: (open: boolean) => void
  close: () => void
  target: AddTarget
  account: Connection | null
  picks: readonly SelectableItem[]
  catalog: ServiceCatalog
  state: CatalogSnapshot
  project: ReturnType<typeof useServiceAttachments>
  choose: (target: AddTarget) => void
  toggle: (item: SelectableItem) => void
  confirm: () => Promise<void>
}

function useAddModel({ projectId, onSelected, openRequest }: WorkspaceAddProps): AddModel {
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<AddTarget>(FIRST_ACCOUNT)
  const [picks, setPicks] = useState<readonly SelectableItem[]>([])
  const close = useCallback(() => setOpen(false), [])
  const enabled = useWorkspaceFetchEnabled() && projectId !== null
  const { catalog, state } = useServiceCatalog(open && enabled)
  const project = useServiceAttachments(projectId, onSelected)
  useEffect(() => {
    if (open && enabled) void project.session.load()
  }, [open, enabled, project.session])
  // Keyed by sequence, not object identity: a re-render never re-opens a closed panel.
  const requestedTab = openRequest?.tab
  const requestSequence = openRequest?.sequence
  useEffect(() => {
    if (requestSequence === undefined || !requestedTab) return
    setTarget(requestedTab === 'hardware' ? { kind: 'hardware' } : FIRST_ACCOUNT)
    setOpen(true)
  }, [requestSequence, requestedTab])
  const account = resolveAccount(target, state.accounts)
  const accountId = account?.id
  const tree = account?.document_tree
  useEffect(() => {
    if (open && accountId && !tree) void catalog.loadDocuments(accountId)
  }, [open, accountId, tree, catalog])
  const choose = (next: AddTarget): void => {
    setTarget(next)
    setPicks([])
  }
  const toggle = (item: SelectableItem): void =>
    setPicks((current) =>
      current.some((pick) => pick.id === item.id)
        ? current.filter((pick) => pick.id !== item.id)
        : [...current, item]
    )
  const confirm = async (): Promise<void> => {
    if (!account) return
    const items = picks
    // ponytail: sequential — ServiceProject serialises on busyId; parallel picks need it relaxed.
    for (const item of items) await project.session.select(account, item)
    setPicks([])
    if (project.session.snapshot().error) return
    useShellStore.getState().setToast({
      kind: 'ok',
      title: `Added ${countOf(items.length, 'document')} from ${accountName(account)}`,
      body: 'Now in the graph.'
    })
    close()
  }
  return {
    open,
    setOpen,
    close,
    target,
    account,
    picks,
    catalog,
    state,
    project,
    choose,
    toggle,
    confirm
  }
}

function AddPane({
  model,
  hardware,
  solusUpload,
  solusTarget
}: Pick<WorkspaceAddProps, 'hardware' | 'solusUpload'> & {
  model: AddModel
  solusTarget: string
}): React.JSX.Element {
  const { target, account, catalog, state, project, picks, toggle } = model
  if (target.kind === 'hardware')
    return (
      <div className="add-modal-pane" role="tabpanel">
        {hardware ?? <p>No hardware added.</p>}
      </div>
    )
  if (target.kind === 'solus')
    return (
      <SolusUploadPane
        target={solusTarget}
        onChoose={() => solusUpload?.choose()}
        onDrop={(files) => void solusUpload?.importFiles(files)}
      />
    )
  if (!account)
    return (
      <div className="add-modal-pane" role="tabpanel">
        <p>Connect an account in Home, or pick .solus or Hardware on the left.</p>
      </div>
    )
  return (
    <AddDocumentsPane
      key={account.id}
      account={account}
      listing={state.documents[account.id]}
      catalog={catalog}
      project={project}
      picks={picks}
      onToggle={toggle}
    />
  )
}

function AddFooter({
  model,
  solusUpload,
  solusTarget
}: Pick<WorkspaceAddProps, 'solusUpload'> & {
  model: AddModel
  solusTarget: string
}): React.JSX.Element {
  const { target, account, picks, project, close, confirm } = model
  return (
    <footer className="add-modal-footer">
      <span className="add-modal-target">
        Adds to <b>{targetName(target, account, solusTarget)}</b>
      </span>
      {project.state.busyId && <p role="status">Importing document…</p>}
      {project.state.error && <p role="alert">{project.state.error}</p>}
      <button type="button" className="add-modal-cancel" onClick={close}>
        Cancel
      </button>
      {target.kind === 'solus' && (
        <button
          type="button"
          className="add-modal-cta"
          disabled={!solusUpload}
          onClick={() => solusUpload?.choose()}
        >
          Choose files
        </button>
      )}
      {target.kind === 'account' && (
        <button
          type="button"
          className="add-modal-cta"
          disabled={!account || picks.length === 0 || project.state.busyId !== null}
          onClick={() => void confirm()}
        >
          {picks.length ? `Add ${countOf(picks.length, 'document')}` : 'Select documents'}
        </button>
      )}
    </footer>
  )
}

export function WorkspaceAdd(props: WorkspaceAddProps): React.JSX.Element {
  const model = useAddModel(props)
  const { open, setOpen, close, account, target, state, catalog, choose } = model
  const enabled = useWorkspaceFetchEnabled() && props.projectId !== null
  const solusTarget = props.solusUpload?.target ?? 'Documentation'
  return (
    <div className="workspace-add">
      <button type="button" aria-expanded={open} disabled={!enabled} onClick={() => setOpen(true)}>
        <Icons.plus size={13} />
        Add
      </button>
      {open && (
        <ModalShell
          width={820}
          pad={0}
          labelledBy="workspace-add-title"
          closeOnEscape
          onClose={close}
        >
          <div className="add-modal">
            <header className="add-modal-header">
              <strong id="workspace-add-title">Add to graph</strong>
              <button type="button" aria-label="Close Add" onClick={close}>
                ✕
              </button>
            </header>
            <div className="add-modal-body">
              <AddSourceRows
                state={state}
                selected={account ? { kind: 'account', id: account.id } : target}
                onSelect={choose}
                onRefresh={() => void catalog.loadAccounts(true)}
              />
              <AddPane
                model={model}
                hardware={props.hardware}
                solusUpload={props.solusUpload}
                solusTarget={solusTarget}
              />
            </div>
            <AddFooter model={model} solusUpload={props.solusUpload} solusTarget={solusTarget} />
          </div>
        </ModalShell>
      )}
    </div>
  )
}
