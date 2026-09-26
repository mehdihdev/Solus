import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  readHardwareTopology,
  type HardwareTopology,
  type HardwareTopologyNode
} from '../../../lib/api/hardwareTopology'
import { ROBOT_CATEGORY_LABELS, type RobotCategory } from '../../../lib/api/hardware'
import { useSettingsStore } from '../../../store/settingsStore'
import { GraphNavigator, type GraphNavigatorProps } from '../navigation/GraphNavigator'
import { topologyProjection } from './topologyProjection'
import { HostAttachmentCard } from './HostAttachmentCard'
import { ExtractionReviewCard } from './ExtractionReviewCard'
import { PresenceCard } from './PresenceCard'
import { useHardwareGeneration } from '../hardware/useHardwareGeneration'

export function RobotTopologyGraph(props: GraphNavigatorProps): React.JSX.Element {
  const { authEpoch } = useHardwareGeneration(props.projectId)
  return <TopologyGraph key={`${props.projectId}:${authEpoch}`} {...props} />
}

function useTopologies(props: GraphNavigatorProps): {
  topologies: HardwareTopology[]
  error: boolean
  loading: boolean
  setRetry: (update: (value: number) => number) => void
} {
  const [topologies, setTopologies] = useState<HardwareTopology[]>([])
  const [error, setError] = useState(false)
  const [completed, setCompleted] = useState<{
    entities: GraphNavigatorProps['entities']
    retry: number
  } | null>(null)
  const [retry, setRetry] = useState(0)
  const robotIds = useMemo(
    () =>
      props.entities
        .filter(
          (entity) =>
            entity.type === 'physical_robot' &&
            (!entity.project_id || entity.project_id === props.projectId)
        )
        .map((entity) => entity.id),
    [props.entities, props.projectId]
  )
  useEffect(() => {
    const controller = new AbortController()
    void Promise.allSettled(
      robotIds.map((id) => readHardwareTopology(props.projectId, id, controller.signal))
    ).then((results) => {
      if (controller.signal.aborted) return
      setTopologies(
        results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []))
      )
      setError(results.some((result) => result.status === 'rejected'))
      setCompleted({ entities: props.entities, retry })
    })
    return () => controller.abort()
  }, [props.projectId, props.entities, robotIds, retry])
  const loading =
    robotIds.length > 0 && (completed?.entities !== props.entities || completed?.retry !== retry)
  return { topologies, error: !loading && error, loading, setRetry }
}

function TopologyGraph(props: GraphNavigatorProps): React.JSX.Element {
  const mode = useSettingsStore((state) => state.solMode)
  const { topologies, error, loading, setRetry } = useTopologies(props)
  const [category, setCategory] = useState<string | null>(null)
  const scopeGraph = useCallback(
    (rootId: string | null) =>
      topologyProjection(props.entities, props.relations, topologies, category, rootId),
    [props.entities, props.relations, topologies, category]
  )
  const { categories, edges, nodes } = topologyMetadata(topologies)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, minWidth: 0 }}>
      {loading && <p role="status">Loading hardware topology…</p>}
      {error && (
        <p role="alert">
          Topology unavailable.{' '}
          {mode === 'Guide'
            ? 'Your saved graph is still available. Retry to load physical connections.'
            : 'Saved graph retained.'}{' '}
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            Retry topology
          </button>
        </p>
      )}
      {topologies.some((topology) => topology.nodes.length === 0) && (
        <p role="status">
          No mapped hardware topology.{' '}
          {mode === 'Guide'
            ? 'Existing parts remain available; add reviewed wiring evidence to map their connections.'
            : 'Existing parts remain available.'}
        </p>
      )}
      {categories.length > 0 && (
        <div role="group" aria-label="Hardware categories">
          <button type="button" aria-pressed={category === null} onClick={() => setCategory(null)}>
            All hardware
          </button>
          {categories.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={category === value}
              onClick={() => setCategory(value)}
            >
              {ROBOT_CATEGORY_LABELS[value as RobotCategory] ?? value}
            </button>
          ))}
        </div>
      )}
      <GraphNavigator
        {...props}
        scopeGraph={scopeGraph}
        scopeRootIds={topologies
          .filter((topology) => topology.roots.length > 0)
          .map((topology) => topology.robot_id)}
        renderContent={(entity) => {
          const node = nodes.get(entity.id)
          return node ? (
            <>
              <TopologyNodeContent
                node={node}
                edges={edges.filter((edge) => edge.target === node.id)}
              />
              {node.role === 'brain' && (
                <ExtractionReviewCard
                  projectId={props.projectId}
                  brainId={node.id}
                  onConfirmed={() => setRetry((value) => value + 1)}
                  robots={topologies
                    .filter((topology) => topology.nodes.some((item) => item.id === node.id))
                    .map((topology) => ({
                      id: topology.robot_id,
                      name:
                        props.entities.find((item) => item.id === topology.robot_id)?.name ??
                        'Robot'
                    }))}
                />
              )}
              {node.role === 'brain' &&
                node.brain_kind !== 'host' &&
                node.channel === 'usb_serial' && (
                  <PresenceCard
                    projectId={props.projectId}
                    brainId={node.id}
                    robots={topologies
                      .filter((topology) => topology.nodes.some((item) => item.id === node.id))
                      .map((topology) => ({
                        id: topology.robot_id,
                        name:
                          props.entities.find((item) => item.id === topology.robot_id)?.name ??
                          'Robot'
                      }))}
                  />
                )}
              {node.role === 'brain' &&
                node.brain_kind !== 'host' &&
                supportsHostConnection(node.channel) && (
                  <HostAttachmentCard
                    projectId={props.projectId}
                    endpointId={node.id}
                    robots={topologies
                      .filter((topology) => topology.nodes.some((item) => item.id === node.id))
                      .map((topology) => ({
                        id: topology.robot_id,
                        name:
                          props.entities.find((item) => item.id === topology.robot_id)?.name ??
                          'Robot'
                      }))}
                    onConfirmed={() => setRetry((value) => value + 1)}
                  />
                )}
            </>
          ) : (
            props.renderContent?.(entity)
          )
        }}
      />
    </div>
  )
}

function TopologyNodeContent({
  node,
  edges
}: {
  node: HardwareTopologyNode
  edges: HardwareTopology['edges']
}): React.JSX.Element {
  return (
    <div className="graph-node-content">
      <p>{node.brain_kind ? `${node.brain_kind.toUpperCase()} brain` : node.role}</p>
      {node.role === 'brain' && <p>Software: {node.software ?? 'unknown'}</p>}
      <p>Channel: {node.channel ?? 'unknown'}</p>
      {node.presence && <p>{node.presence}</p>}
      {edges.map((edge) => (
        <p key={edge.id}>
          Protocol: {edge.protocol ?? 'unknown'} · Address: {edge.address ?? 'unknown'}
        </p>
      ))}
      {(node.evidence?.length ?? 0) > 0 && (
        <details>
          <summary>Show evidence</summary>
          {node.evidence?.map((item, index) => (
            <p key={index}>
              {item.by}
              {item.source ? ` · ${item.source}` : ''}
            </p>
          ))}
        </details>
      )}
    </div>
  )
}

function topologyMetadata(topologies: HardwareTopology[]): {
  categories: string[]
  edges: HardwareTopology['edges']
  nodes: Map<string, HardwareTopologyNode>
} {
  const categories = [
    ...new Set(
      topologies.flatMap((topology) =>
        topology.nodes.flatMap((node) => (node.category ? [node.category] : []))
      )
    )
  ].sort()
  const edges = [
    ...new Map(
      topologies.flatMap((topology) => topology.edges.map((edge) => [edge.id, edge] as const))
    ).values()
  ]
  const nodes = new Map(
    topologies.flatMap((topology) => topology.nodes.map((node) => [node.id, node] as const))
  )
  return { categories, edges, nodes }
}

function supportsHostConnection(channel: string | null | undefined): boolean {
  return ['usb_serial', 'usb_can'].includes(channel ?? '')
}
