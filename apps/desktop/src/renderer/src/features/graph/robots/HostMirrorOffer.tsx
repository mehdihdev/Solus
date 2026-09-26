import { useEffect, useId, useRef, useState } from 'react'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useSettingsStore } from '../../../store/settingsStore'
import { sendMessage } from '../../sol/solChatStore'
import { workspaceSessionGeneration } from '../workspaceSession'
import { prepareMirrorOffer, type MirrorOffer, type MirrorOfferInput } from './hostMirrorSnippet'
interface Props {
  projectId: string
  sourceId: string
  robotId: string
  generation: number
  files: string[]
}
const EMPTY: MirrorOfferInput = {
  file: '',
  object: '',
  anchor: '',
  method: '',
  mappings: '',
  argument: '',
  deviceId: '',
  port: '',
  capacity: '128'
}
export function HostMirrorOffer({
  projectId,
  sourceId,
  robotId,
  generation,
  files
}: Props): React.JSX.Element {
  const mode = useSettingsStore((state) => state.solMode)
  const id = useId()
  const [input, setInput] = useState(EMPTY)
  const [offer, setOffer] = useState<MirrorOffer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'pending' | 'requested' | 'uncertain'>('idle')
  const alive = useRef(true),
    pending = useRef<number | null>(null),
    epoch = useRef(0)
  const scope = `${projectId}:${sourceId}:${robotId}:${generation}`
  const currentScope = useRef(scope)
  currentScope.current = scope
  useEffect(() => {
    alive.current = true
    pending.current = null
    setInput(EMPTY)
    setOffer(null)
    setState('idle')
    setError(null)
    return () => {
      alive.current = false
      epoch.current += 1
    }
  }, [scope])
  function change(field: keyof MirrorOfferInput, value: string): void {
    epoch.current += 1
    setInput((previous) => ({ ...previous, [field]: value }))
    setOffer(null)
    setError(null)
    setState('idle')
  }
  function preview(): void {
    if (pending.current !== null || generation !== workspaceSessionGeneration()) return
    try {
      setOffer(prepareMirrorOffer(input, sourceId, robotId))
      setError(null)
    } catch (cause) {
      setOffer(null)
      setError(cause instanceof Error ? cause.message : 'Check adapter choices.')
    }
  }
  async function request(): Promise<void> {
    if (
      !offer ||
      pending.current !== null ||
      state !== 'idle' ||
      generation !== workspaceSessionGeneration()
    )
      return
    const ticket = ++epoch.current
    pending.current = ticket
    setState('pending')
    const current = (): boolean =>
      alive.current &&
      epoch.current === ticket &&
      currentScope.current === scope &&
      generation === workspaceSessionGeneration()
    try {
      openSolReview()
      const sent = await sendMessage(projectId, offer.prompt, 'do', [], false, undefined, {
        forceConfirmation: true
      })
      if (!sent) throw new Error('Unverified request')
      if (current()) setState('requested')
    } catch {
      if (current()) {
        setState('uncertain')
        setError('Request could not be verified. Inspect SOL before requesting another review.')
      }
    } finally {
      if (pending.current === ticket) pending.current = null
    }
  }
  const fields: [keyof MirrorOfferInput, string][] = [
    ['file', 'Control loop file'],
    ['object', 'Control object'],
    ['anchor', 'Insert after this exact line'],
    ['method', 'Method to observe'],
    ['argument', 'Argument position or keyword (blank observes return)'],
    ['deviceId', 'Device ID'],
    ['port', 'Loopback UDP port'],
    ['capacity', 'Queue capacity']
  ]
  return (
    <section aria-label="Host telemetry mirror">
      <h4>Mirror existing control I/O</h4>
      <p>
        Choose an existing local Python loop and its explicit adapter. The file diff requires
        separate approval in SOL.
      </p>
      {mode === 'Guide' && (
        <p>
          Observe a synchronous method that returns a dictionary, or select the dictionary argument
          it receives. The mirror does not start your loop or add hardware reads. Keep the handle
          for your existing teardown and call solus_mirror.close() when observation should end.
        </p>
      )}
      <fieldset disabled={state !== 'idle'}>
        {fields.map(([field, label]) => (
          <label key={field}>
            {label}
            <input
              aria-label={label}
              list={field === 'file' ? id : undefined}
              value={input[field]}
              maxLength={field === 'deviceId' ? 512 : 400}
              onChange={(event) => change(field, event.target.value)}
            />
          </label>
        ))}
        <datalist id={id}>
          {files
            .filter((file) => typeof file === 'string' && file.endsWith('.py'))
            .map((file) => (
              <option key={file} value={file} />
            ))}
        </datalist>
        <label>
          Signal mappings
          <textarea
            aria-label="Signal mappings"
            value={input.mappings}
            maxLength={75000}
            onChange={(event) => change('mappings', event.target.value)}
          />
        </label>
        <p>
          One signal=dictionary_key|unit per line. Omit |unit when unknown. Use the same device ID
          and UDP port in the saved robot’s JSON-lines receiver configuration.
        </p>
        <button type="button" onClick={preview}>
          Preview mirror shim
        </button>
      </fieldset>
      {offer && (
        <>
          <pre aria-label="Proposed mirror shim">{offer.snippet}</pre>
          <button type="button" disabled={state !== 'idle'} onClick={() => void request()}>
            Request file diff review
          </button>
        </>
      )}
      {state === 'requested' && (
        <p role="status">
          Review requested in SOL. The shim is not installed until the file confirmation succeeds.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}

function openSolReview(): void {
  getDesktopSolBridge()?.open()
}
