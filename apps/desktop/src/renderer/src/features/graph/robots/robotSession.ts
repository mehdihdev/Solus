import { apiBaseUrl, createApiClient, type ApiClient } from '../../../lib/api/client'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  createPhysicalRobot,
  deletePhysicalRobot,
  renamePhysicalRobot
} from '../../../lib/api/physicalRobots'
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
}
type Current = () => boolean
function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}
/** One mounted workspace owns its robot writes. */
export class RobotSession {
  private state: RobotView = { busy: null, error: null }
  private listeners = new Set<() => void>()
  private active = false
  private lifecycle = 0
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
      if (current()) this.onChanged(entity.id)
    })
  private requireEditable(entity: Entity): void {
    if (!editableRobot(entity, this.projectId))
      throw new Error(
        'This robot cannot be edited here. Refresh the workspace and check your access.'
      )
  }
}
