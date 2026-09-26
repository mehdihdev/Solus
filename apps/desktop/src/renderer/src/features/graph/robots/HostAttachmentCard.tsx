import { useEffect, useRef, useState } from 'react'
import { HostMirrorOffer } from './HostMirrorOffer'
import { useWorkspaceSessionGeneration } from '../workspaceSession'
import {
  proposeHostTopology,
  confirmHostTopology,
  type HostAttachment,
  type HostProposal
} from '../../../lib/api/hostTopology'
import { isRootProject } from '../../../lib/api/resources.localfolder'
import { ApiError } from '../../../lib/api/envelope.types'
import { getDesktopFolderBridge } from '../../../lib/desktopBridge'
import { useSettingsStore } from '../../../store/settingsStore'
import { useAuthStore } from '../../../store/authStore'
import { ProjectFolderCard } from '../../project/ProjectFolderCard'
import { useLocalFolder, useMachineIdentity } from '../../project/useLocalFolder'
import { useProjectFolderStore } from '../../project/projectFolderStore'
import { useHardwareGeneration } from '../hardware/useHardwareGeneration'

interface Props {
  projectId: string
  endpointId: string
  robots: { id: string; name: string }[]
  onConfirmed: () => void
}
const identity = { machine: async () => (await getDesktopFolderBridge()?.machine()) ?? null }

export function HostAttachmentCard(props: Props): React.JSX.Element {
  const { generation, authEpoch } = useHardwareGeneration(`${props.projectId}:${props.endpointId}`)
  return (
    <Attachment
      key={`${props.projectId}:${props.endpointId}:${authEpoch}`}
      {...props}
      generation={generation}
    />
  )
}

function Attachment(props: Props & { generation: React.RefObject<number> }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  return open ? (
    <AttachmentForm {...props} onCancel={() => setOpen(false)} />
  ) : (
    <button type="button" onClick={() => setOpen(true)}>
      Connect this computer
    </button>
  )
}

function AttachmentForm({
  projectId,
  endpointId,
  robots,
  onConfirmed,
  onCancel,
  generation
}: Props & { generation: React.RefObject<number>; onCancel: () => void }): React.JSX.Element {
  const mode = useSettingsStore((state) => state.solMode)
  const workspaceGeneration = useWorkspaceSessionGeneration()
  const authenticated = useAuthStore((state) => state.status === 'authenticated')
  const folder = useProjectFolderStore((state) => state.folders[projectId])
  const local = useLocalFolder(projectId, Boolean(folder))
  const { machine } = useMachineIdentity(identity)
  const [owner, setOwner] = useState('')
  const robotId = robots.length === 1 ? robots[0].id : owner
  const [software, setSoftware] = useState('')
  const [mcu, setMcu] = useState(false)
  const [review, setReview] = useState<{
    proposal: HostProposal
    input: HostAttachment
    key: string
    fingerprint: string
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const pending = useRef<AbortController | null>(null)
  const choices =
    local.view?.detected.filter(
      (item) => isRootProject(item) || ['python', 'arduino'].includes(item.tool)
    ) ?? []
  const source = local.view?.source
  function localConnectionReady(): boolean {
    return source?.status === 'connected' && Boolean(local.view?.bridge.connected)
  }
  function connectionAvailable(): boolean {
    return Boolean(
      authenticated &&
        getDesktopFolderBridge() &&
        machine &&
        folder &&
        local.status === 'ready' &&
        localConnectionReady() &&
        robots.some((robot) => robot.id === robotId) &&
        choices.some((item) => item.entity_id === software)
    )
  }
  const available = connectionAvailable()
  // Local path is only a scope-change sentinel. It is never sent in API input.
  const fingerprint = JSON.stringify([
    projectId,
    endpointId,
    robotId,
    folder,
    machine?.id,
    local.status,
    source,
    local.view?.bridge.connected,
    choices,
    software,
    mcu,
    available
  ])
  const current = useRef(fingerprint)
  current.current = fingerprint
  useEffect(() => {
    setReview(null)
    setBusy(false)
    setError(null)
    setSaved(false)
    return () => {
      pending.current?.abort()
      pending.current = null
    }
  }, [fingerprint])
  const validReview = review?.fingerprint === fingerprint ? review : null

  function showSubmitError(cause: unknown, confirm: boolean): void {
    if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status)) {
      setReview(null)
      setError('Connection evidence changed or is unavailable. Review the connection again.')
    } else
      setError(
        confirm
          ? 'Connection was not confirmed. Retry this review, or cancel and review fresh evidence.'
          : 'Cannot review this connection. Check the local folder and companion, then try again.'
      )
  }
  function submissionBlocked(confirm: boolean): boolean {
    return Boolean(pending.current) || !available || (confirm && !validReview)
  }
  async function submit(confirm: boolean): Promise<void> {
    if (!machine || !source || submissionBlocked(confirm)) return
    const controller = new AbortController()
    pending.current = controller
    const epoch = generation.current
    const stillCurrent = (): boolean =>
      !controller.signal.aborted && epoch === generation.current && fingerprint === current.current
    setBusy(true)
    setError(null)
    const input: HostAttachment = {
      endpoint_id: endpointId,
      machine_id: machine.id,
      local_source_id: source.id,
      software_entity_id: software,
      ...(mcu ? { endpoint_brain_kind: 'mcu' } : {})
    }
    async function executeConnection(): Promise<void> {
      if (confirm && validReview) {
        await confirmHostTopology(
          projectId,
          robotId,
          { ...validReview.input, proposal_digest: validReview.proposal.proposal_digest },
          validReview.key,
          controller.signal
        )
        if (!stillCurrent()) return
        setReview(null)
        setSaved(true)
        onConfirmed()
      } else {
        const proposal = await proposeHostTopology(projectId, robotId, input, controller.signal)
        if (stillCurrent()) setReview({ proposal, input, key: crypto.randomUUID(), fingerprint })
      }
    }
    try {
      await executeConnection()
    } catch (cause) {
      if (stillCurrent()) showSubmitError(cause, confirm)
    } finally {
      if (pending.current === controller) pending.current = null
      if (stillCurrent()) setBusy(false)
    }
  }
  function renderInputs(): React.ReactNode {
    return (
      <>
        {mode === 'Guide' && (
          <p>
            Choose local control software, then review the physical connection. A folder association
            does not verify a running process.
          </p>
        )}
        {!getDesktopFolderBridge() && (
          <p>The desktop companion is required to identify this computer.</p>
        )}
        {!folder && <ProjectFolderCard projectId={projectId} />}
        {robots.length > 1 && (
          <label>
            Robot for this connection
            <select
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              disabled={busy}
            >
              <option value="">Choose a robot</option>
              {robots.map((robot) => (
                <option key={robot.id} value={robot.id}>
                  {robot.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Local control software
          <select
            value={software}
            onChange={(event) => setSoftware(event.target.value)}
            disabled={busy}
          >
            <option value="">Choose local software</option>
            {choices.map((item) => (
              <option key={item.entity_id} value={item.entity_id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={mcu}
            onChange={(event) => setMcu(event.target.checked)}
            disabled={busy}
          />
          This endpoint is an MCU
        </label>
        {!local.view?.bridge.connected && (
          <p>Connect the local companion to review this connection.</p>
        )}
      </>
    )
  }
  function renderProposal(): React.ReactNode {
    return (
      <>
        {validReview && (
          <div aria-label="Proposed connection">
            <p>{validReview.proposal.host_name}</p>
            <ul>
              {validReview.proposal.topology.edges.map((edge) => (
                <li key={edge.id}>
                  {
                    validReview.proposal.topology.nodes.find((node) => node.id === edge.source)
                      ?.name
                  }{' '}
                  →{' '}
                  {
                    validReview.proposal.topology.nodes.find((node) => node.id === edge.target)
                      ?.name
                  }{' '}
                  ({edge.protocol ?? 'unknown'})
                </li>
              ))}
            </ul>
            {validReview.proposal.notes.map((note, index) => (
              <p key={index}>{note}</p>
            ))}
          </div>
        )}
      </>
    )
  }
  function renderOutcome(): React.ReactNode {
    return (
      <>
        {error && <p role="alert">{error}</p>}
        {saved ? (
          <p role="status">Computer connection saved.</p>
        ) : validReview ? (
          <button type="button" disabled={busy || !available} onClick={() => void submit(true)}>
            Confirm graph connection
          </button>
        ) : (
          <button type="button" disabled={busy || !available} onClick={() => void submit(false)}>
            Review connection
          </button>
        )}
        {saved && available && source && (
          <HostMirrorOffer
            key={fingerprint}
            projectId={projectId}
            sourceId={source.id}
            robotId={robotId}
            generation={workspaceGeneration}
            files={choices.filter((item) => item.tool === 'python').map((item) => item.path)}
          />
        )}
      </>
    )
  }
  return (
    <section aria-label="Connect computer to endpoint">
      <h4>Connect this computer</h4>
      {renderInputs()}
      {renderProposal()}
      {renderOutcome()}
      <button
        type="button"
        onClick={() => {
          pending.current?.abort()
          onCancel()
        }}
      >
        Cancel
      </button>
    </section>
  )
}
