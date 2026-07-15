// Onboarding step 1 — "Connect your tools". The connector tiles share one UI,
// listed from the LIVE backend catalog (SOLUSDEV-100; curated fallback offline).
// GitHub drives the REAL OAuth connector (SOLUSDEV-103) when a project is
// linked and the Electron OAuth bridge is present; committed-export EDA
// connectors (KiCad, Altium) drive the REAL file-pick connect; everything else
// stays simulated. On entering this step we ensure a project exists so a real
// connect has something to attach a source to; if the API/auth is unavailable
// we fall back to the simulated tiles so onboarding still completes (dev bypass).
import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import { ConnectTile } from './ConnectTile'
import { MIN_SOURCES_TO_BUILD, type Integration } from './integrations.constants'
import { type CatalogEntry } from './integrationCatalog'
import { useIntegrationCatalog } from './useIntegrationCatalog'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'
import { ensureWorkspace } from './provisioning'
import { useEdaConnect } from './useEdaConnect'
import { useGithubConnect } from './useGithubConnect'

const CONNECT_STEP_MS = 650
const COMPLETE_DELAY_MS = 350
/** Committed netlist exports a user can pick (KiCad XML netlist first). */
const EXPORT_FILE_ACCEPT = '.xml,.net'

interface ConnectStepProps {
  onBuild: () => void
}

export function ConnectStep({ onBuild }: ConnectStepProps): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const beginConnect = useOnboardingStore((s) => s.beginConnect)
  const setConnectStep = useOnboardingStore((s) => s.setConnectStep)
  const completeConnect = useOnboardingStore((s) => s.completeConnect)
  const description = useOnboardingStore((s) => s.description)
  const solMode = useSettingsStore((s) => s.solMode)
  const workspace = useWorkspaceStore()
  const catalog = useIntegrationCatalog()
  const github = useGithubConnect()
  const eda = useEdaConnect()
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
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

  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.length = 0
    }
  }, [])

  const simulateConnect = (integ: Integration): void => {
    beginConnect(integ.id)
    integ.steps.forEach((_, i) => {
      if (i > 0) {
        timers.current.push(setTimeout(() => setConnectStep(integ.id, i), i * CONNECT_STEP_MS))
      }
    })
    timers.current.push(
      setTimeout(
        () => completeConnect(integ.id),
        integ.steps.length * CONNECT_STEP_MS + COMPLETE_DELAY_MS
      )
    )
  }

  const connect = (integ: CatalogEntry): void => {
    // Real flows need a linked project (and GitHub the OAuth bridge); otherwise
    // (dev bypass / web build) the tile degrades to the simulated animation.
    if (
      integ.mode === 'github-oauth' &&
      workspace.linked &&
      workspace.project &&
      getDesktopOAuthBridge()
    ) {
      void github.start(workspace.project.id)
      return
    }
    if (integ.mode === 'export-file' && workspace.linked && workspace.project) {
      // Committed-export EDA connect: pick the netlist export, then sync it.
      pendingProvider.current = integ.id
      exportInput.current?.click()
      return
    }
    simulateConnect(integ)
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
