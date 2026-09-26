import { useEffect, useState } from 'react'
import type { SolMode } from '../../../store/settingsStore'
import { useHardwareGeneration } from './useHardwareGeneration'
import { notifyProposalSourcesChanged } from './useProposalSources'
import { Button } from '../../../components/ui/Button'
import './hardware.css'

type Sources = Window['solus']['hardware']['sources']
type Picked = Extract<Awaited<ReturnType<Sources['pick']>>, { ok: true }>['value']
type Source = Picked['source']
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/iu
const EMPTY_REFS: readonly string[] = []

function failure(reason: string): string {
  switch (reason) {
    case 'source_changed':
      return 'File contents changed. Relink and review the new file.'
    case 'newer':
      return 'This source registry needs a newer desktop app.'
    case 'invalid':
    case 'relink_required':
      return 'The local source needs relinking.'
    case 'unauthorized':
      return 'Sign in with access to this project to manage local files.'
    case 'stale_scope':
      return 'Project or account changed. Try again in the current project.'
    case 'not_found':
      return 'This source is not linked on this account and machine.'
    case 'busy':
      return 'Finish the open file picker first.'
    default:
      return 'Local files are unavailable. Try again in the desktop app.'
  }
}

interface SourceListState {
  generation: React.RefObject<number>
  sources: Source[]
  setSources: React.Dispatch<React.SetStateAction<Source[]>>
  accountId: string | null
  busy: boolean
  setBusy: React.Dispatch<React.SetStateAction<boolean>>
  error: string | null
  setError: React.Dispatch<React.SetStateAction<string | null>>
  status: string | null
  setStatus: React.Dispatch<React.SetStateAction<string | null>>
  reloadSources: () => void
}

function useLocalSourceList(projectId: string): SourceListState {
  const { generation, authEpoch } = useHardwareGeneration(projectId)
  const [sources, setSources] = useState<Source[]>([])
  const [accountId, setAccountId] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    const ticket = generation.current
    const bridge = window.solus?.hardware?.sources
    if (!bridge) return
    void bridge.list().then(
      (result) => {
        if (!active || ticket !== generation.current) return
        if (result.ok && result.value.projectId === projectId) {
          setAccountId(result.value.accountId)
          setSources(result.value.sources)
        } else setError(failure(result.ok ? 'stale_scope' : result.reason))
        setBusy(false)
      },
      () => {
        if (active && ticket === generation.current) {
          setError(failure('unavailable'))
          setBusy(false)
        }
      }
    )
    return () => {
      active = false
    }
  }, [projectId, authEpoch, reload, generation])

  return {
    generation,
    sources,
    setSources,
    accountId,
    busy: window.solus?.hardware?.sources ? busy : false,
    setBusy,
    error,
    setError,
    status: window.solus?.hardware?.sources ? status : failure('unavailable'),
    setStatus,
    reloadSources: () => {
      setSources([])
      setAccountId(null)
      setError(null)
      setStatus(null)
      setBusy(true)
      setReload((value) => value + 1)
    }
  }
}

function useLocalSourceActions(projectId: string): Pick<
  SourceListState,
  'sources' | 'accountId' | 'busy' | 'error' | 'status' | 'reloadSources'
> & {
  act: (kind: 'pick' | 'recheck', ref?: string) => Promise<void>
} {
  const {
    generation,
    sources,
    setSources,
    accountId,
    busy,
    setBusy,
    error,
    setError,
    status,
    setStatus,
    reloadSources
  } = useLocalSourceList(projectId)
  const receive = (
    result: Awaited<ReturnType<Sources['pick']>>,
    kind: 'pick' | 'recheck'
  ): void => {
    if (!result.ok) {
      if (result.reason !== 'cancelled') setError(failure(result.reason))
    } else if (result.value.projectId !== projectId || result.value.accountId !== accountId) {
      setError(failure('stale_scope'))
    } else {
      notifyProposalSourcesChanged()
      const source = result.value.source
      setSources((previous) => [
        ...previous.filter((row) => row.sourceRef !== source.sourceRef),
        source
      ])
      setStatus(
        kind === 'recheck'
          ? 'Selected file bytes verified.'
          : 'Local file linked. Shared configuration is unchanged.'
      )
    }
  }

  const act = async (kind: 'pick' | 'recheck', ref?: string): Promise<void> => {
    const bridge = window.solus?.hardware?.sources
    if (!bridge || accountId === null || busy) return
    const ticket = generation.current
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const result = await requestSource(bridge, kind, ref)
      if (ticket !== generation.current) return
      receive(result, kind)
    } catch {
      if (ticket === generation.current) setError(failure('unavailable'))
    } finally {
      if (ticket === generation.current) setBusy(false)
    }
  }
  return { sources, accountId, busy, error, status, reloadSources, act }
}

interface HardwareSourcesProps {
  projectId: string
  mode: SolMode
  onSelect?: (sourceRef: string) => void
  onSourceChange?: () => void
  title?: string
  sourceRefs?: readonly string[]
}

export function HardwareSourcesPanel(props: HardwareSourcesProps): React.JSX.Element {
  const { authEpoch } = useHardwareGeneration(props.projectId)
  return (
    <ScopedHardwareSourcesPanel key={JSON.stringify([props.projectId, authEpoch])} {...props} />
  )
}

function ScopedHardwareSourcesPanel({
  projectId,
  mode,
  onSelect,
  onSourceChange,
  title = 'Local calibration sources',
  sourceRefs = EMPTY_REFS
}: HardwareSourcesProps): React.JSX.Element {
  const { sources, accountId, busy, error, status, reloadSources, act } =
    useLocalSourceActions(projectId)
  const missing = [
    ...new Set(
      sourceRefs
        .map((ref) => (ref.startsWith('source:') ? ref.slice(7) : ''))
        .filter((ref) => UUID.test(ref))
    )
  ].filter((ref) => !sources.some((source) => source.sourceRef === ref))
  return (
    <section aria-label={title} className="hardware-sources">
      <h3>{title}</h3>
      <p>
        {mode === 'Guide'
          ? 'Choose files on this computer for your signed-in account. Listing a file does not verify its contents; use Verify before relying on it.'
          : 'Account-local files. Listed files are not yet verified.'}
      </p>
      {error && <p role="alert">{error}</p>}
      {status && <p role="status">{status}</p>}
      <ul>
        {sources.map((source) => (
          <li key={source.sourceRef}>
            <span>{source.displayName}</span>{' '}
            {onSelect && (
              <Button
                size="sm"
                kind="soft"
                disabled={busy}
                onClick={() => onSelect(`source:${source.sourceRef}`)}
                aria-label={`Select ${source.displayName}`}
              >
                Select
              </Button>
            )}{' '}
            <Button
              size="sm"
              kind="ghost"
              disabled={busy}
              onClick={() => {
                onSourceChange?.()
                void act('recheck', source.sourceRef)
              }}
              aria-label={`Verify ${source.displayName}`}
            >
              Verify
            </Button>{' '}
            <Button
              size="sm"
              kind="bare"
              disabled={busy}
              onClick={() => {
                onSourceChange?.()
                void act('pick', source.sourceRef)
              }}
              aria-label={`Relink ${source.displayName}`}
            >
              Relink
            </Button>
          </li>
        ))}
        {missing.map((ref, index) => (
          <li key={ref}>
            Unlinked source {index + 1}{' '}
            <Button
              size="sm"
              kind="soft"
              disabled={busy || accountId === null}
              onClick={() => {
                onSourceChange?.()
                void act('pick', ref)
              }}
              aria-label={`Relink source ${index + 1}`}
            >
              Relink
            </Button>
          </li>
        ))}
      </ul>
      <Button
        size="sm"
        kind="soft"
        disabled={busy || accountId === null}
        onClick={() => {
          onSourceChange?.()
          void act('pick')
        }}
      >
        Choose local file
      </Button>{' '}
      <Button
        size="sm"
        kind="bare"
        disabled={busy}
        onClick={() => {
          onSourceChange?.()
          notifyProposalSourcesChanged()
          reloadSources()
        }}
      >
        Refresh sources
      </Button>
    </section>
  )
}

function requestSource(
  bridge: Sources,
  kind: 'pick' | 'recheck',
  ref?: string
): ReturnType<Sources['pick']> {
  return kind === 'pick' ? bridge.pick(ref ? { sourceRef: ref } : {}) : bridge.recheck(ref ?? '')
}
