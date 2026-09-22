import { api, type ApiClient } from './client'
import type { HostedOAuthStart, HostedStatus } from './resources'

function path(connectionId: string, server: string): string {
  return `/users/me/connections/${encodeURIComponent(connectionId)}/hosted/${encodeURIComponent(server)}`
}
export function getAccountHosted(
  connectionId: string,
  server: string,
  client: ApiClient = api
): Promise<HostedStatus> {
  return client.request(path(connectionId, server))
}
export function startAccountHosted(
  connectionId: string,
  server: string,
  client: ApiClient = api
): Promise<HostedOAuthStart> {
  return client.request(`${path(connectionId, server)}/oauth/start`, { method: 'POST' })
}
export function exchangeAccountHosted(
  connectionId: string,
  server: string,
  body: { state: string; code: string },
  client: ApiClient = api
): Promise<HostedStatus> {
  return client.request(`${path(connectionId, server)}/oauth/exchange`, { method: 'POST', body })
}
export function probeAccountHosted(
  connectionId: string,
  server: string,
  client: ApiClient = api
): Promise<HostedStatus> {
  return client.request(`${path(connectionId, server)}/probe`, { method: 'POST' })
}
