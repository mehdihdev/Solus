import { apiBaseUrl, createApiClient, type ApiClient, type Page } from '../../../lib/api/client'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  createPhysicalRobot,
  deletePhysicalRobot,
  renamePhysicalRobot
} from '../../../lib/api/physicalRobots'
import { listUnassignedParts } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'

export function editableRobot(entity: Entity, projectId: string): boolean {
  return (
    entity.type === 'physical_robot' &&
    entity.origin === 'manual' &&
    entity.source_id === null &&
    entity.project_id === projectId &&
    Number.isSafeInteger(entity.version) &&
    (entity.version ?? -1) >= 0
  )
}
interface RobotError {
  key: string
  message: string
  conflict: boolean
}
export interface RobotView {
  busy: string | null
  error: RobotError | null
  parts: Entity[]
  loading: boolean
  readError: string | null
  cursors: (string | null)[]
  next: string | null
}
type Current = () => boolean
function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}
function verifyPage(
  page: Page<Entity[]>,
  projectId: string,
  cursors: (string | null)[]
): string | null {
  if (page.data.length > 24 || page.data.some((part) => part.project_id !== projectId))
    throw new Error('The unassigned parts response could not be verified. Please retry.')
  const next = page.meta.has_next ? page.meta.next_cursor : null
  if (page.meta.has_next && (!next || cursors.includes(next)))
    throw new Error('The next page of unassigned parts could not be read. Please retry.')
  return next ?? null
}

/** One mounted workspace owns its writes and orphan-page reads. */
export class RobotSession {
  private state: RobotView = {
    busy: null,
    error: null,
    parts: [],
    loading: false,
    readError: null,
    cursors: [null],
    next: null
  }
  private listeners = new Set<() => void>()
  private active = false
  private lifecycle = 0
  private readSequence = 0
  private mutation: Promise<boolean> | null = null

  constructor(
    readonly projectId: string,
    private currentWorkspace: Current,
    private onChanged: (removedId?: string) => void,
    private onReveal: (entityId: string) => void
  ) {}
  snapshot = (): RobotView => this.state
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  activate = (): void => {
    this.active = true
    this.lifecycle += 1
  }
  dispose = (): void => {
    this.active = false
    this.lifecycle += 1
  }
  private guard(): Current {
    const lifecycle = this.lifecycle
    return () => this.active && lifecycle === this.lifecycle && this.currentWorkspace()
  }
  private publish(update: Partial<RobotView>): void {
    this.state = { ...this.state, ...update }
    this.listeners.forEach((listener) => listener())
  }
  private client(current: Current): ApiClient {
    return createApiClient({
      baseUrl: apiBaseUrl,
      getToken: () => {
        if (!current()) throw new Error('The workspace session has changed.')
        return useAuthStore.getState().accessToken
      }
    })
  }
  load = async (cursors: (string | null)[] = [null]): Promise<void> => {
    const current = this.guard()
    if (!current()) return
    const sequence = ++this.readSequence
    this.publish({ loading: true, readError: null })
    try {
      // Fresh clients prevent an older identical GET from absorbing an invalidation.
      const page = await listUnassignedParts(
        this.projectId,
        cursors.at(-1) ?? null,
        this.client(current)
      )
      if (!current() || sequence !== this.readSequence) return
      const next = verifyPage(page, this.projectId, cursors)
      this.publish({
        parts: [...new Map(page.data.map((part) => [part.id, part])).values()],
        next,
        cursors,
        loading: false
      })
    } catch (error) {
      if (current() && sequence === this.readSequence)
        this.publish({ loading: false, readError: messageOf(error) })
    }
  }
  next = (): void => {
    if (!this.state.loading && this.state.next)
      void this.load([...this.state.cursors, this.state.next])
  }
  previous = (): void => {
    if (!this.state.loading && this.state.cursors.length > 1)
      void this.load(this.state.cursors.slice(0, -1))
  }
  retry = (): void => {
    void this.load(this.state.cursors)
  }
  reveal = (entityId: string): void => {
    if (this.guard()() && this.state.parts.some((part) => part.id === entityId))
      this.onReveal(entityId)
  }
  private run(
    key: string,
    operation: (client: ApiClient, current: Current) => Promise<void>
  ): Promise<boolean> {
    if (this.state.busy)
      return this.state.busy === key && this.mutation ? this.mutation : Promise.resolve(false)
    const current = this.guard()
    if (!current()) return Promise.resolve(false)
    this.publish({ busy: key, error: null })
    this.mutation = (async () => {
      try {
        await operation(this.client(current), current)
        return current()
      } catch (error) {
        if (current()) {
          const conflict =
            error instanceof ApiError && error.status === 409 && error.code === 'conflict'
          this.publish({
            error: {
              key,
              conflict,
              message: conflict
                ? 'This robot changed. Review the refreshed name before saving again. To delete it, close this confirmation and review the robot first.'
                : messageOf(error)
            }
          })
          if (conflict) this.onChanged()
        }
        return false
      } finally {
        if (current()) this.publish({ busy: null })
        this.mutation = null
      }
    })()
    return this.mutation
  }
  create = (): Promise<boolean> =>
    this.run('create', async (client, current) => {
      const entity = await createPhysicalRobot(this.projectId, client)
      if (!current()) return
      if (!editableRobot(entity, this.projectId))
        throw new Error(
          'The created robot could not be verified. Refresh the workspace before trying again.'
        )
      this.onChanged()
      this.onReveal(entity.id)
    })
  rename = (entity: Entity, name: string): Promise<boolean> =>
    this.run(entity.id, async (client, current) => {
      this.requireEditable(entity)
      if (!name.trim() || name.trim().length > 512)
        throw new Error('Use a robot name between 1 and 512 characters.')
      await renamePhysicalRobot(this.projectId, entity, name.trim(), client)
      if (current()) this.onChanged()
    })
  remove = (entity: Entity): Promise<boolean> =>
    this.run(entity.id, async (client, current) => {
      this.requireEditable(entity)
      await deletePhysicalRobot(this.projectId, entity, client)
      if (!current()) return
      this.onChanged(entity.id)
      void this.load()
    })
  private requireEditable(entity: Entity): void {
    if (!editableRobot(entity, this.projectId))
      throw new Error(
        'This robot cannot be edited here. Refresh the workspace and check your access.'
      )
  }
}
