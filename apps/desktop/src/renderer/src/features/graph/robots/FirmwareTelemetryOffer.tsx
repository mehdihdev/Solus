import { useEffect, useRef, useState } from 'react'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useSettingsStore } from '../../../store/settingsStore'
import { sendMessage } from '../../sol/solChatStore'
import { useLocalFolder, type LocalFolderController } from '../../project/useLocalFolder'
import { useProjectFolderStore } from '../../project/projectFolderStore'
import { ProjectFolderCard } from '../../project/ProjectFolderCard'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import {
  prepareFirmwareOffer,
  type FirmwareOfferInput,
  type FirmwareOffer
} from './firmwareTelemetrySnippet'
const EMPTY: FirmwareOfferInput = { file: '', deviceId: '', baud: '', anchor: '', mappings: '' }
export function FirmwareTelemetryOffer({ projectId }: { projectId: string }): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  const folder = useProjectFolderStore((s) => s.folders[projectId])
  const local = useLocalFolder(projectId, Boolean(folder))
  const source = local.view?.source
  const files = sketchFiles(local)
  const available = localFirmwareAvailable(local)
  return (
    <section aria-label="Existing firmware telemetry">
      <h4>Add telemetry to an existing local sketch</h4>
      <p>
        Choose the local source again. A reference repository or hardware evidence file is not a
        machine write grant.
      </p>
      {!available || !source ? (
        <>
          <ProjectFolderCard projectId={projectId} />
          <p>
            Connect and synchronize a local folder with its companion to select an existing sketch.
          </p>
        </>
      ) : (
        <Offer
          key={JSON.stringify([generation, projectId, source, files])}
          projectId={projectId}
          sourceId={source.id}
          sourceName={source.name}
          files={files}
          generation={generation}
        />
      )}
    </section>
  )
}
function sketchFiles(local: LocalFolderController): string[] {
  return (
    local.view?.detected
      .filter((item) => item.tool === 'arduino' && item.path.endsWith('.ino'))
      .map((item) => item.path) ?? []
  )
}
function localFirmwareAvailable(local: LocalFolderController): boolean {
  return (
    local.status === 'ready' &&
    local.view?.source?.type === 'local' &&
    local.view.source.status === 'connected' &&
    local.view.bridge.connected
  )
}
function canRequestOffer(
  valid: boolean,
  pending: boolean,
  status: string,
  offer: FirmwareOffer | null,
  selected: string,
  sourceId: string
): boolean {
  return valid && !pending && status === 'idle' && offer !== null && selected === sourceId
}

function Offer({
  projectId,
  sourceId,
  sourceName,
  files,
  generation
}: {
  projectId: string
  sourceId: string
  sourceName: string
  files: string[]
  generation: number
}): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const [selected, setSelected] = useState(''),
    [input, setInput] = useState(EMPTY),
    [offer, setOffer] = useState<FirmwareOffer | null>(null),
    [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'pending' | 'requested' | 'uncertain'>('idle')
  const alive = useRef(true),
    pending = useRef(false)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const valid = (): boolean => alive.current && generation === workspaceSessionGeneration()
  const change = (field: keyof FirmwareOfferInput, value: string): void => {
    setInput((old) => ({ ...old, [field]: value }))
    setOffer(null)
    setError(null)
  }
  const preview = (): void => {
    if (!valid() || pending.current || selected !== sourceId) return
    try {
      setOffer(prepareFirmwareOffer(input, sourceId, files))
      setError(null)
    } catch (cause) {
      setOffer(null)
      setError(cause instanceof Error ? cause.message : 'Check firmware choices.')
    }
  }
  const request = async (): Promise<void> => {
    if (!offer || !canRequestOffer(valid(), pending.current, status, offer, selected, sourceId))
      return
    pending.current = true
    setStatus('pending')
    setError(null)
    try {
      getDesktopSolBridge()?.open()
      const sent = await sendMessage(projectId, offer.prompt, 'do', [], false, undefined, {
        forceConfirmation: true
      })
      if (!sent) throw new Error('Uncertain')
      if (valid()) setStatus('requested')
    } catch {
      if (valid()) {
        setStatus('uncertain')
        setError('Request could not be verified. Inspect SOL before requesting another review.')
      }
    } finally {
      pending.current = false
    }
  }
  return (
    <>
      <p>
        This adds serial output and may change loop timing. It does not change the existing baud or
        add hardware reads. Serial command buses are not eligible.
      </p>
      {mode === 'Guide' && (
        <p>
          Select existing numeric scalar variables after your sketch has computed them. SOL must
          verify their scope and show the complete file diff before any edit. This does not install
          the library or flash firmware.
        </p>
      )}
      <fieldset disabled={status !== 'idle'}>
        <label>
          Firmware local source
          <select
            aria-label="Firmware local source"
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value)
              setInput(EMPTY)
              setOffer(null)
              setError(null)
            }}
          >
            <option value="">Choose local source</option>
            <option value={sourceId}>{sourceName}</option>
          </select>
        </label>
        {selected && (
          <>
            <label>
              Existing sketch
              <select
                aria-label="Existing sketch"
                value={input.file}
                onChange={(e) => change('file', e.target.value)}
              >
                <option value="">Choose .ino file</option>
                {files.map((file) => (
                  <option key={file} value={file}>
                    {file}
                  </option>
                ))}
              </select>
            </label>
            {files.length === 0 && (
              <p>
                No .ino files in the current local manifest. Synchronize the intended local sketch
                first.
              </p>
            )}
            {(
              [
                ['deviceId', 'Firmware device ID'],
                ['baud', 'Existing serial baud'],
                ['anchor', 'Publish after exact line']
              ] as const
            ).map(([field, label]) => (
              <label key={field}>
                {label}
                <input
                  aria-label={label}
                  value={input[field]}
                  maxLength={400}
                  onChange={(e) => change(field, e.target.value)}
                />
              </label>
            ))}
            <label>
              Numeric signal mappings
              <textarea
                aria-label="Numeric signal mappings"
                maxLength={8000}
                value={input.mappings}
                onChange={(e) => change('mappings', e.target.value)}
              />
            </label>
            <p>
              One channel=variable|unit per line; omit |unit when unknown. Numeric variables only,
              no function calls or expressions.
            </p>
            <button onClick={preview}>Preview telemetry additions</button>
          </>
        )}
      </fieldset>
      {offer && (
        <>
          <pre aria-label="Proposed include additions">{offer.include}</pre>
          <pre aria-label="Proposed setup additions">{offer.setup}</pre>
          <pre aria-label="Proposed loop additions">{offer.loop}</pre>
          <button disabled={status !== 'idle'} onClick={() => void request()}>
            Request firmware file diff
          </button>
        </>
      )}
      {status === 'pending' && <p role="status">Requesting file review…</p>}
      {status === 'requested' && (
        <p role="status">
          File review requested in SOL. No library installation or firmware flash was requested.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </>
  )
}
