import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { listEntities, type CreateBenchSessionInput, type Entity } from '../../lib/api/resources'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'

interface Props {
  projectId: string
  onConnect: (input: CreateBenchSessionInput) => Promise<string | null>
}

export function SavedRobotConnections({ projectId, onConnect }: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  const [query, setQuery] = useState('')
  const scope = JSON.stringify([projectId, generation, query])
  const [result, setResult] = useState<{
    scope: string
    robots: Entity[]
    error: string | null
  } | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<{ scope: string; message: string } | null>(null)
  useEffect(() => {
    let live = true
    void listEntities(projectId, { type: 'physical_robot', q: query, limit: 24 }).then(
      (robots) => {
        if (!live || generation !== workspaceSessionGeneration()) return
        setResult({
          scope,
          error: null,
          robots: robots
            .slice(0, 24)
            .filter(
              (robot) =>
                robot.project_id === projectId &&
                robot.type === 'physical_robot' &&
                robot.origin === 'manual' &&
                robot.source_id === null
            )
        })
      },
      () => {
        if (live) setResult({ scope, robots: [], error: 'Saved robots could not be loaded.' })
      }
    )
    return () => {
      live = false
    }
  }, [projectId, query, generation, scope])
  const connect = async (robot: Entity): Promise<void> => {
    if (pending !== null || generation !== workspaceSessionGeneration()) return
    setPending(robot.id)
    setError(null)
    try {
      const message = await onConnect({
        mode: 'real',
        config: { provider: 'robot', robot_entity_id: robot.id }
      })
      if (generation === workspaceSessionGeneration() && message) setError({ scope, message })
    } catch {
      if (generation === workspaceSessionGeneration())
        setError({ scope, message: 'The saved robot could not connect.' })
    } finally {
      setPending(null)
    }
  }
  const current = result?.scope === scope ? result : null
  return (
    <section aria-label="Saved robots" style={{ marginTop: 14 }}>
      <h3>Saved robots</h3>
      <p>Use a robot&apos;s saved protocol and calibration to read its telemetry.</p>
      <input
        aria-label="Find saved robot"
        placeholder="Find saved robot"
        maxLength={120}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <SavedRobotResults current={current} pending={pending} connect={connect} />
      {error?.scope === scope && <p role="alert">{error.message}</p>}
    </section>
  )
}

function SavedRobotResults({
  current,
  pending,
  connect
}: {
  current: { robots: Entity[]; error: string | null } | null
  pending: string | null
  connect: (robot: Entity) => Promise<void>
}): React.JSX.Element {
  return (
    <>
      {' '}
      {!current && <p role="status">Loading saved robots…</p>}
      {current?.error && <p role="alert">{current.error}</p>}
      {current && !current.error && current.robots.length === 0 && <p>No saved robots match.</p>}
      {current?.robots.map((robot) => (
        <div
          key={robot.id}
          style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}
        >
          <span>{robot.name}</span>
          <Button
            size="sm"
            kind="ghost"
            aria-label={`Connect saved ${robot.name}`}
            disabled={pending !== null}
            onClick={() => void connect(robot)}
          >
            Connect
          </Button>
        </div>
      ))}
      {current && current.robots.length === 24 && (
        <p>Showing up to 24 matches. Narrow your search to find another robot.</p>
      )}
    </>
  )
}
