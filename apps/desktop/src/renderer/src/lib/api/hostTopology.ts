import {
  api,
  apiBaseUrl,
  apiToken,
  joinUrl,
  unwrapEnvelope,
  type ApiClient,
  type ApiClientOptions
} from './client'
import { validTopology, type HardwareTopology } from './hardwareTopology'
import type { components } from './schema'

export type HostAttachment = components['schemas']['HostAttachment']
export type HostProposal = components['schemas']['HostProposal']
export type HostConfirm = components['schemas']['HostConfirm']

function route(projectId: string, robotId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/hardware/robots/${encodeURIComponent(robotId)}/topology/host`
}

export async function proposeHostTopology(
  projectId: string,
  robotId: string,
  input: HostAttachment,
  signal?: AbortSignal,
  client: ApiClient = api
): Promise<HostProposal> {
  const result = await client.request<unknown>(`${route(projectId, robotId)}/propose`, {
    method: 'POST',
    body: input,
    signal
  })
  if (!result || typeof result !== 'object') throw new Error('Invalid host proposal')
  const value = result as Partial<HostProposal>
  if (!matchesHostInput(value, input) || !validHostEvidence(value, robotId))
    throw new Error('Invalid host proposal')
  return value as HostProposal
}

export async function confirmHostTopology(
  projectId: string,
  robotId: string,
  input: HostConfirm,
  operationKey: string,
  signal?: AbortSignal,
  transport: Partial<ApiClientOptions> = {}
): Promise<HardwareTopology> {
  const token = await (transport.getToken ?? apiToken)()
  signal?.throwIfAborted()
  const response = await (transport.fetchImpl ?? fetch)(
    joinUrl(transport.baseUrl ?? apiBaseUrl, `${route(projectId, robotId)}/confirm`),
    {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': operationKey,
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify(input)
    }
  )
  const result = unwrapEnvelope<unknown>(response.status, await response.json())
  if (!validTopology(result) || result.robot_id !== robotId)
    throw new Error('Invalid confirmed host topology')
  return result
}

function matchesHostInput(value: Partial<HostProposal>, input: HostAttachment): boolean {
  return !(
    value.endpoint_id !== input.endpoint_id ||
    value.machine_id !== input.machine_id ||
    value.local_source_id !== input.local_source_id ||
    (value.software_entity_id ?? null) !== (input.software_entity_id ?? null) ||
    (value.endpoint_brain_kind ?? null) !== (input.endpoint_brain_kind ?? null)
  )
}

function validHostEvidence(value: Partial<HostProposal>, robotId: string): boolean {
  return !(
    typeof value.host_name !== 'string' ||
    typeof value.proposal_digest !== 'string' ||
    !/^[a-f0-9]{64}$/.test(value.proposal_digest) ||
    !Array.isArray(value.notes) ||
    value.notes.length > 32 ||
    !value.notes.every((note) => typeof note === 'string' && note.length <= 2048) ||
    !validTopology(value.topology) ||
    value.topology.robot_id !== robotId
  )
}
