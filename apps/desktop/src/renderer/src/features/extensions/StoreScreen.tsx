// SOLUSDEV-235 — the Store (`MainScreen 'store'`). Capabilities are installed,
// not built in: this page lists what the open project has installed and what
// the catalog suggests, gated on the sources actually connected — never on
// what sells. Clicking a card opens ExtensionDetail in place; the selection
// lives in extensionsStore so the shell breadcrumb can read it.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { CreateExtensionModal } from './CreateExtensionModal'
import { ExtensionCard, SectionLabel, type StoreLayout } from './ExtensionCard'
import { ExtensionDetail } from './ExtensionDetail'
import { partitionViews } from './extensionLogic'
import { useExtensionsStore } from './extensionsStore'
import { useExtensions, type ExtensionsData } from './useExtensions'
import type { ExtensionView } from './extension.types'

/** How many installed extensions show before "See all installed". */
export const INSTALLED_PREVIEW_COUNT = 4

export function StoreScreen(): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  if (!project) {
    return (
      <ScreenEmptyState
        icon={<Icons.plus size={30} />}
        title="Select a project"
        body="Open a project from Home to install and configure its extensions."
      />
    )
  }
  return <StoreView projectId={project.id} />
}

function StoreView({ projectId }: { projectId: string }): React.JSX.Element {
  const data = useExtensions(projectId)
  const selectedId = useExtensionsStore((s) => s.selectedId)
  const select = useExtensionsStore((s) => s.select)
  const selected = selectedId ? data.views.find((v) => v.manifest.id === selectedId) : undefined

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '26px 24px 48px' }}>
        {selected ? (
          <ExtensionDetail view={selected} actions={data.actions} onBack={() => select(null)} />
        ) : (
          <Catalog data={data} onOpen={select} />
        )}
      </div>
    </div>
  )
}

function Catalog({
  data,
  onOpen
}: {
  data: ExtensionsData
  onOpen: (id: string) => void
}): React.JSX.Element {
  const [layout, setLayout] = useState<StoreLayout>('grid')
  const [showAll, setShowAll] = useState(false)
  const [creating, setCreating] = useState(false)
  const { installed, popular } = partitionViews(data.views)
  const visibleInstalled = showAll ? installed : installed.slice(0, INSTALLED_PREVIEW_COUNT)

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
            Store
          </h1>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
            Capabilities are installed, not built in. Suggestions come from what&apos;s connected —
            never from what sells.
          </div>
        </div>
        <LayoutToggle value={layout} onChange={setLayout} />
        <Button kind="primary" size="md" onClick={() => setCreating(true)}>
          <Icons.plus size={12} /> Create extension
        </Button>
      </div>

      {data.sourcesStatus !== 'ready' && (
        <Card pad={12} style={{ marginTop: 18 }}>
          <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
            {data.sourcesStatus === 'loading'
              ? 'Checking this project’s connected sources…'
              : "Solus can't see this project's sources right now, so source requirements below are shown as unmet."}
          </div>
        </Card>
      )}

      <SectionLabel>INSTALLED</SectionLabel>
      <ExtensionGrid
        testId="store-installed"
        views={visibleInstalled}
        layout={layout}
        onOpen={onOpen}
        emptyText="Nothing installed in this project yet."
      />
      {installed.length > INSTALLED_PREVIEW_COUNT && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 16 }}>
          <Button kind="soft" size="sm" onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Show fewer' : `See all installed (${installed.length})`}
          </Button>
        </div>
      )}

      <SectionLabel>POPULAR EXTENSIONS</SectionLabel>
      <ExtensionGrid
        testId="store-popular"
        views={popular}
        layout={layout}
        onOpen={onOpen}
        emptyText="Everything in the catalog is installed in this project."
      />

      {creating && <CreateExtensionModal onClose={() => setCreating(false)} />}
    </>
  )
}

function LayoutToggle({
  value,
  onChange
}: {
  value: StoreLayout
  onChange: (layout: StoreLayout) => void
}): React.JSX.Element {
  const options: ReadonlyArray<{ id: StoreLayout; label: string; icon: React.ReactNode }> = [
    { id: 'grid', label: 'Grid view', icon: <Icons.grid size={12} /> },
    { id: 'list', label: 'List view', icon: <Icons.list size={12} /> }
  ]
  return (
    <div
      role="radiogroup"
      aria-label="Layout"
      style={{
        display: 'inline-flex',
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        overflow: 'hidden',
        alignSelf: 'center'
      }}
    >
      {options.map((o, i) => {
        const active = value === o.id
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={o.label}
            title={o.label}
            onClick={() => onChange(o.id)}
            className="interactive"
            style={{
              width: 38,
              height: 32,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: active ? 'var(--sur2)' : 'transparent',
              color: active ? 'var(--tx)' : 'var(--mut)',
              border: 'none',
              borderRight: i < options.length - 1 ? '1px solid var(--bd)' : 'none',
              cursor: 'pointer'
            }}
          >
            {o.icon}
          </button>
        )
      })}
    </div>
  )
}

function ExtensionGrid({
  testId,
  views,
  layout,
  onOpen,
  emptyText
}: {
  testId: string
  views: readonly ExtensionView[]
  layout: StoreLayout
  onOpen: (id: string) => void
  emptyText: string
}): React.JSX.Element {
  if (views.length === 0) {
    return (
      <Card pad={20} data-testid={testId} data-layout={layout}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>{emptyText}</div>
      </Card>
    )
  }
  return (
    <div
      data-testid={testId}
      data-layout={layout}
      style={{
        display: 'grid',
        gridTemplateColumns: layout === 'grid' ? 'repeat(2, minmax(0, 1fr))' : 'minmax(0, 1fr)',
        gap: layout === 'grid' ? 14 : 8
      }}
    >
      {views.map((v) => (
        <ExtensionCard key={v.manifest.id} view={v} layout={layout} onOpen={onOpen} />
      ))}
    </div>
  )
}
