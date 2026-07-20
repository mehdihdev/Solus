// Onboarding step 1 — "Connect your tools". Tiles are listed from the LIVE
// backend catalog (SOLUSDEV-100; curated drivable fallback offline). GitHub
// drives the REAL OAuth connector (SOLUSDEV-103); committed-export EDA
// connectors (KiCad, Altium) drive the REAL file-pick connect. There is no
// simulated connect (SOLUSDEV-152): when a real connect can't run (workspace
// unlinked / no Electron bridge) the tile reports an honest, retryable error.
// On entering this step we ensure a project exists so a real connect has
// something to attach a source to.
import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import { ConnectTile } from './ConnectTile'
import { MIN_SOURCES_TO_BUILD } from './integrations.constants'
import { type CatalogEntry } from './integrationCatalog'
import { useIntegrationCatalog } from './useIntegrationCatalog'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'
import { ensureWorkspace } from './provisioning'
import { useEdaConnect } from './useEdaConnect'
import { useGithubConnect } from './useGithubConnect'

/** Committed netlist exports a user can pick (KiCad XML netlist first). */
const EXPORT_FILE_ACCEPT = '.xml,.net'
const NOT_LINKED_ERROR = 'Solus API unreachable — retry once you are back online.'
const NO_BRIDGE_ERROR = 'GitHub connect needs the Solus desktop app.'

interface ConnectStepProps {
  onBuild: () => void
}

export function ConnectStep({ onBuild }: ConnectStepProps): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const failConnect = useOnboardingStore((s) => s.failConnect)
  const description = useOnboardingStore((s) => s.description)
  const solMode = useSettingsStore((s) => s.solMode)
  const workspace = useWorkspaceStore()
  const catalog = useIntegrationCatalog()
  const github = useGithubConnect()
  const eda = useEdaConnect()
  const exportInput = useRef<HTMLInputElement | null>(null)
  // Which export-file provider's picker is open (set on tile click).
  const pendingProvider = useRef<string | null>(null)

  // Ensure a project exists as soon as we reach the connect step, reusing one
  // already created earlier in the flow. Best-effort; never blocks the UI.
  useEffect(() => {
    let cancelled = false
    void ensureWorkspace({
      description,
      solMode,
      existing: { teamId: workspace.teamId, project: workspace.project }
    }).then((result) => {
      if (cancelled) return
      workspace.setLinked(result.linked)
      if (result.teamId) workspace.setTeamId(result.teamId)
      if (result.project) workspace.setProject(result.project)
    })
    return () => {
      cancelled = true
    }
    // Run once on mount; workspace setters are stable store actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const connect = (integ: CatalogEntry): void => {
    // Real flows need a linked project (and GitHub the OAuth bridge). When a
    // precondition is missing the tile errors honestly and stays retryable —
    // nothing is ever faked.
    if (!workspace.linked || !workspace.project) {
      failConnect(integ.id, NOT_LINKED_ERROR)
      return
    }
    if (integ.mode === 'github-oauth') {
      if (!getDesktopOAuthBridge()) {
        failConnect(integ.id, NO_BRIDGE_ERROR)
        return
      }
      void github.start(workspace.project.id)
      return
    }
    // Committed-export EDA connect: pick the netlist export, then sync it.
    pendingProvider.current = integ.id
    exportInput.current?.click()
  }

  const onExportPicked = async (input: HTMLInputElement): Promise<void> => {
    const provider = pendingProvider.current
    pendingProvider.current = null
    const file = input.files?.[0]
    input.value = ''
    if (!provider || !file || !workspace.project) return
    const content = await file.text()
    await eda.start(workspace.project.id, provider, { fileName: file.name, content })
  }

  const count = connectedCount(connections)
  const ready = canBuildModel(connections)

  return (
    <div style={{ width: 660 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        Connect your tools
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
        Each source becomes a domain in your context model. Connect at least two — cross-domain
        checks need something to cross.
      </p>
      <input
        ref={exportInput}
        type="file"
        accept={EXPORT_FILE_ACCEPT}
        aria-label="Choose a committed netlist export"
        style={{ display: 'none' }}
        onChange={(e) => void onExportPicked(e.currentTarget)}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 24 }}>
        {catalog.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onConnect={() => connect(integ)}
            onChooseRepo={github.chooseRepo}
            onRetry={() => connect(integ)}
          />
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 28
        }}
      >
        <Mono size={10} color={ready ? 'var(--ok)' : 'var(--mut)'}>
          {count} OF {catalog.length} CONNECTED{' '}
          {ready ? '— READY' : `(${MIN_SOURCES_TO_BUILD}+ RECOMMENDED)`}
        </Mono>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* Connections never gate the workspace (FND-08): tools can always
              be connected later from the Sources page. */}
          {!ready && (
            <Button kind="ghost" size="lg" onClick={onBuild} aria-label="Skip for now">
              Skip for now
            </Button>
          )}
          <Button kind="primary" size="lg" disabled={!ready} onClick={onBuild}>
            Build context model <Icons.arrowR size={14} />
          </Button>
        </div>
      </div>
      <p style={{ color: 'var(--mut)', fontSize: 11.5, marginTop: 10, textAlign: 'right' }}>
        You can connect tools anytime later — skipping takes you straight to your workspace.
      </p>
    </div>
  )
}
