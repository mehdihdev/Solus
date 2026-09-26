import { useEffect, useRef, useState, type ReactNode } from 'react'
import { PresenceWiringCard } from './PresenceWiringCard'
import {
  listPresenceProfiles,
  preparePresence,
  type PresencePlan,
  type PresenceProfile,
  type PresenceInput
} from '../../../lib/api/presence'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useSettingsStore } from '../../../store/settingsStore'
import { sendMessage } from '../../sol/solChatStore'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
interface Props {
  projectId: string
  brainId: string
  robots: { id: string; name: string }[]
}
export function PresenceCard(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Card
      key={`${generation}:${props.projectId}:${props.brainId}:${props.robots.map((r) => r.id).join(',')}`}
      {...props}
      generation={generation}
    />
  )
}
function Card({
  projectId,
  brainId,
  robots,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const [profiles, setProfiles] = useState<PresenceProfile[] | null>(null)
  const [robot, setRobot] = useState(robots.length === 1 ? robots[0].id : '')
  const [profile, setProfile] = useState<PresenceInput['profile_id'] | ''>('')
  const [kind, setKind] = useState<PresenceInput['kind'] | ''>('')
  const [wiringId, setWiringId] = useState<string | null>(null)
  const [plan, setPlan] = useState<PresencePlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [requested, setRequested] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const epoch = useRef(0),
    pending = useRef(false),
    alive = useRef(true)
  const current = (ticket: number): boolean =>
    alive.current && ticket === epoch.current && generation === workspaceSessionGeneration()
  useEffect(() => {
    alive.current = true
    let cancelled = false
    void listPresenceProfiles(projectId)
      .then((value) => {
        if (!cancelled && alive.current && generation === workspaceSessionGeneration())
          setProfiles(value)
      })
      .catch(() => {
        if (!cancelled && alive.current)
          setError('Firmware profiles unavailable. Check the local compiler and connection.')
      })
    return () => {
      cancelled = true
      alive.current = false
      epoch.current += 1
    }
  }, [projectId, generation])
  const invalidate = (): void => {
    epoch.current += 1
    pending.current = false
    setPlan(null)
    setRequested(false)
    setBusy(false)
    setError(null)
  }
  const prepare = async (): Promise<void> => {
    if (
      !profile ||
      !kind ||
      !canPrepare(pending.current, robot, kind, profiles, profile, Boolean(wiringId))
    )
      return
    const ticket = ++epoch.current
    pending.current = true
    setBusy(true)
    setError(null)
    setPlan(null)
    setRequested(false)
    try {
      const result = await preparePresence(projectId, robot, brainId, {
        profile_id: profile,
        kind,
        channel: 'uno.alive',
        ...(kind === 'topology' && wiringId ? { wiring_proposal_id: wiringId } : {})
      })
      if (current(ticket)) setPlan(result)
    } catch {
      if (current(ticket))
        setError(
          'Firmware preparation unavailable. Check the board profile, accepted connection and local compiler. Configured driver boards are excluded.'
        )
    } finally {
      if (current(ticket)) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  const review = async (): Promise<void> => {
    if (!plan || requested || pending.current || !current(epoch.current)) return
    const ticket = epoch.current
    pending.current = true
    setBusy(true)
    setRequested(true)
    setError(null)
    try {
      getDesktopSolBridge()?.open()
      const sent = await sendMessage(
        projectId,
        `Request the complete confirmation preview for hardware.flash_presence with plan_id ${plan.plan_id}. This requests review only; wait for my explicit confirmation before flashing.`,
        'do'
      )
      if (!sent) throw new Error('Review was not confirmed')
    } catch {
      if (current(ticket))
        setError(
          'Review request could not be verified. Check the SOL conversation before requesting another review.'
        )
    } finally {
      if (current(ticket)) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  return (
    <PresenceContent
      wiringAccepted={Boolean(wiringId)}
      wiringCard={
        robot && profile && profiles?.some((p) => p.id === profile && p.available) ? (
          <PresenceWiringCard
            key={`${robot}:${profile}`}
            projectId={projectId}
            robotId={robot}
            brainId={brainId}
            profileId={profile}
            onAccepted={(id) => {
              invalidate()
              setWiringId(id)
            }}
          />
        ) : null
      }
      {...{
        robots,
        robot,
        setRobot: (value: string) => {
          setWiringId(null)
          setRobot(value)
        },
        profile,
        setProfile: (value: typeof profile) => {
          setWiringId(null)
          setProfile(value)
        },
        kind,
        setKind,
        profiles,
        plan,
        busy,
        requested,
        error,
        mode,
        invalidate,
        prepare,
        review
      }}
    />
  )
}
function PresenceContent({
  wiringCard,
  wiringAccepted,
  robots,
  robot,
  setRobot,
  profile,
  setProfile,
  kind,
  setKind,
  profiles,
  plan,
  busy,
  requested,
  error,
  mode,
  invalidate,
  prepare,
  review
}: {
  wiringCard: ReactNode
  wiringAccepted: boolean
  robots: Props['robots']
  robot: string
  setRobot: (value: string) => void
  profile: PresenceInput['profile_id'] | ''
  setProfile: (value: PresenceInput['profile_id'] | '') => void
  kind: PresenceInput['kind'] | ''
  setKind: (value: PresenceInput['kind'] | '') => void
  profiles: PresenceProfile[] | null
  plan: PresencePlan | null
  busy: boolean
  requested: boolean
  error: string | null
  mode: string
  invalidate: () => void
  prepare: () => Promise<void>
  review: () => Promise<void>
}): React.JSX.Element {
  return (
    <section aria-label="Presence firmware">
      <h3>Presence firmware</h3>
      <p>
        {mode === 'Guide'
          ? 'Prepare a small heartbeat or wiring probe for a board you identify. A USB bridge such as CH340 does not establish the board model or whether firmware is empty.'
          : 'Choose the board profile explicitly. USB bridge identity does not establish the board or its firmware.'}
      </p>
      <p>
        Existing firmware will be erased and replaced if you approve the flash. Driver boards are
        excluded.
      </p>
      {robots.length !== 1 && (
        <label>
          Robot
          <select
            aria-label="Presence robot"
            value={robot}
            onChange={(e) => {
              invalidate()
              setRobot(e.target.value)
            }}
          >
            <option value="">Choose robot</option>
            {robots.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Board profile
        <select
          aria-label="Board profile"
          value={profile}
          onChange={(e) => {
            invalidate()
            setProfile(e.target.value as typeof profile)
          }}
        >
          <option value="">Choose profile</option>
          {profiles?.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.available}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <ProfileAvailability profiles={profiles} error={error} />
      {wiringCard}
      <label>
        Presence firmware
        <select
          aria-label="Presence firmware"
          value={kind}
          onChange={(e) => {
            invalidate()
            setKind(e.target.value as typeof kind)
          }}
        >
          <option value="">Choose firmware</option>
          <option value="heartbeat">Heartbeat</option>
          <option value="probe">I2C and analog probe</option>
          <option value="topology" disabled={!wiringAccepted}>
            Read accepted input wiring
          </option>
        </select>
      </label>
      {kind === 'probe' && (
        <p>
          Analog readings are raw values, not proof of attached parts. No I2C responses do not prove
          every pin is unwired.
        </p>
      )}
      <button
        disabled={!canPrepare(busy, robot, kind, profiles, profile, wiringAccepted)}
        onClick={() => void prepare()}
      >
        Prepare firmware
      </button>
      {busy && <p role="status">{requested ? 'Requesting review…' : 'Preparing firmware…'}</p>}
      {error && <p role="alert">{error}</p>}
      {plan && (
        <PreparedPlan plan={plan} busy={busy} requested={requested} error={error} review={review} />
      )}
    </section>
  )
}
function ProfileAvailability({
  profiles,
  error
}: {
  profiles: PresenceProfile[] | null
  error: string | null
}): React.JSX.Element {
  return (
    <>
      {profiles === null && !error && <p role="status">Checking firmware profiles…</p>}
      {profiles?.length === 0 && <p>Local firmware provider unavailable.</p>}
      {profiles
        ?.filter((p) => !p.available)
        .map((p) => (
          <p key={p.id}>{p.reason ?? 'Profile unavailable.'}</p>
        ))}
    </>
  )
}
function PreparedPlan({
  plan,
  busy,
  requested,
  error,
  review
}: {
  plan: PresencePlan
  busy: boolean
  requested: boolean
  error: string | null
  review: () => Promise<void>
}): React.JSX.Element {
  return (
    <div>
      <p>
        Observed target: {plan.target.path} · USB {plan.target.vid.toString(16)}:
        {plan.target.pid.toString(16)} ·{' '}
        {plan.target.serial ?? 'No serial number — identity is tied to this USB port'} ·{' '}
        {plan.target.location ?? 'location unknown'}
      </p>
      <p>
        Binding: {plan.target.binding} · Profile: {plan.profile}
      </p>
      <p>Source SHA256: {plan.source_sha256}</p>
      <p>Binary SHA256: {plan.binary_sha256}</p>
      <pre aria-label="Complete generated source">{plan.source}</pre>
      <p>Preparing and requesting review do not approve a flash.</p>
      <button disabled={busy || requested} onClick={() => void review()}>
        Request flash review
      </button>
      {requested && !busy && !error && (
        <p role="status">
          Review requested. Inspect the SOL confirmation card; firmware has not been approved here.
        </p>
      )}
    </div>
  )
}

function canPrepare(
  busy: boolean,
  robot: string,
  kind: string,
  profiles: PresenceProfile[] | null,
  profile: string,
  wiringAccepted: boolean
): boolean {
  return (
    !busy &&
    Boolean(robot) &&
    Boolean(kind) &&
    (kind !== 'topology' || wiringAccepted) &&
    Boolean(profiles?.some((p) => p.id === profile && p.available))
  )
}
