// SOLUSDEV-246 / STORE ST4 — the BOM tab, a first-party page rendered in-repo
// (features/extensions/firstParty.ts). Every part in the robot, raw materials
// and anything purchased — ONE row per physical part (a fingerprinted servo in
// CAD and the schematic is one row), lifecycle state per row, supplier
// preferences and cost target from the bundle's settings / the repo's
// `[ext.bom]` section, and CSV export. Data: `useBom` over the bundle's own
// routes; nothing here is invented — an empty project is an empty BOM.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import type { BomRowApi } from '../../lib/api/resources.bom'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ModalShell } from '../workspace/modals'
import { PageHeader } from '../extensions/pageview/PageHeader'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import type { FirstPartyPageProps } from '../extensions/firstParty'
import { AddRowModal } from './AddRowModal'
import { BomTable } from './BomTable'
import { csvFilename, formatMoney, totalsLine, viewNote } from './bomLogic'
import { useBom, type BomData } from './useBom'

export function BomScreen({
  projectId,
  publisher,
  onBack,
  onOpenStore
}: FirstPartyPageProps): React.JSX.Element {
  const data = useBom(projectId)
  const projectName = useWorkspaceStore((s) => s.project?.name ?? 'this project')
  return (
    <div
      className="screen-in"
      data-testid="bom-screen"
      style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}
    >
      <PageHeader
        name="BOM"
        iconSvg={null}
        isDev={false}
        version={null}
        publisher={publisher}
        onBack={onBack}
        actions={<HeaderActions data={data} projectName={projectName} />}
      />
      <Body data={data} onOpenStore={onOpenStore} />
    </div>
  )
}

function HeaderActions({
  data,
  projectName
}: {
  data: BomData
  projectName: string
}): React.JSX.Element | null {
  const [note, setNote] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  if (data.status !== 'ready') return null
  const exportCsv = async (): Promise<void> => {
    const outcome = await data.actions.exportCsv(csvFilename(projectName))
    setNote(outcome.ok ? null : outcome.message)
  }
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {note && (
        <span role="status" style={{ fontSize: 11.5, color: 'var(--warn)' }}>
          {note}
        </span>
      )}
      <Button size="sm" kind="ghost" onClick={() => void exportCsv()}>
        <Icons.file size={12} /> Export CSV
      </Button>
      <Button size="sm" kind="primary" onClick={() => setAdding(true)}>
        <Icons.plus size={12} /> Add row
      </Button>
      {adding && <AddRowModal onAdd={data.actions.addRow} onClose={() => setAdding(false)} />}
    </div>
  )
}

/** The honest non-ready states: loading, not installed here, unreachable. */
function NotReady({
  status,
  onOpenStore
}: {
  status: Exclude<BomData['status'], 'ready'>
  onOpenStore?: () => void
}): React.JSX.Element {
  if (status === 'loading') {
    return <ScreenEmptyState title="Loading the BOM…" body="Reading this project's parts." />
  }
  if (status === 'not_installed') {
    return (
      <ScreenEmptyState
        icon={<Icons.hex size={30} />}
        title="BOM isn't installed in this project."
        body="Install or enable it from the Store to see this project's bill of materials."
      >
        {onOpenStore && (
          <Button size="sm" kind="ghost" onClick={onOpenStore} style={{ marginTop: 12 }}>
            Open in Store
          </Button>
        )}
      </ScreenEmptyState>
    )
  }
  return (
    <ScreenEmptyState
      icon={<Icons.warn size={30} />}
      title="Solus can't reach Solus right now."
      body="The BOM lists live parts only; it will fill in once the backend is reachable."
    />
  )
}

function RemoveModal({
  row,
  onClose,
  onConfirm
}: {
  row: BomRowApi
  onClose: () => void
  onConfirm: () => void
}): React.JSX.Element {
  return (
    <ModalShell onClose={onClose}>
      <Mono size={9.5}>REMOVE ROW</Mono>
      <div style={{ fontSize: 13, marginTop: 10, lineHeight: 1.5 }}>
        Remove <strong>{row.name}</strong> from the BOM? Parts from your tools are never removed
        here; this row was added by hand.
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" onClick={onConfirm}>
          Remove row
        </Button>
      </div>
    </ModalShell>
  )
}

function Body({
  data,
  onOpenStore
}: {
  data: BomData
  onOpenStore?: () => void
}): React.JSX.Element {
  const [removing, setRemoving] = useState<BomRowApi | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const { status, view, actions } = data
  if (status !== 'ready' || view === null) {
    return <NotReady status={status === 'ready' ? 'offline' : status} onOpenStore={onOpenStore} />
  }

  const act = async (outcome: Promise<{ ok: boolean; message?: string }>): Promise<void> => {
    const result = await outcome
    setNote(result.ok ? null : (result.message ?? "That didn't work."))
  }
  const line = note ?? viewNote(view)

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 1180, margin: '0 auto', padding: '18px 24px 48px' }}>
        <ConfigLine view={view} />
        {line && (
          <Card pad={12} style={{ marginTop: 12 }}>
            <div role="status" style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
              {line}
            </div>
          </Card>
        )}
        <div style={{ marginTop: 14 }}>
          {view.rows.length === 0 ? (
            <Card pad={20}>
              <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
                No parts yet. Connect a CAD or EDA source and sync it, or add a purchase or raw
                material with <strong>Add row</strong>.
              </div>
            </Card>
          ) : (
            <BomTable
              rows={view.rows}
              states={view.states}
              currency={view.config.currency}
              onState={(key, state) => void act(actions.setState(key, state))}
              onRemove={setRemoving}
            />
          )}
        </div>
      </div>
      {removing && (
        <RemoveModal
          row={removing}
          onClose={() => setRemoving(null)}
          onConfirm={() => {
            void act(actions.removeRow(removing.key))
            setRemoving(null)
          }}
        />
      )}
    </div>
  )
}

/** Supplier preferences, currency, cost target and the totals — configuration
 *  is the bundle's settings (Store › BOM › Settings) or the repo `[ext.bom]`. */
function ConfigLine({ view }: { view: NonNullable<BomData['view']> }): React.JSX.Element {
  const { config } = view
  const suppliers =
    config.preferred_suppliers.length > 0
      ? `Preferred suppliers: ${config.preferred_suppliers.join(', ')}`
      : 'No preferred suppliers set'
  const target =
    config.cost_target === null
      ? 'no cost target'
      : `cost target ${formatMoney(config.cost_target, config.currency)}`
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', alignItems: 'baseline' }}>
      <span style={{ fontSize: 12.5 }}>{totalsLine(view)}</span>
      <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>
        {suppliers} · {config.currency} · {target}
      </span>
    </div>
  )
}
