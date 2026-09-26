import { useEffect, useState } from 'react'
import { getBenchDeviceRecent, type BenchDeviceRecent } from '../../../lib/api/resources'
import { workspaceSessionGeneration } from '../../graph/workspaceSession'
import { jointValue } from './kinematics'
import type { SceneModel } from './types'
import { useBenchRealtimeData } from '../BenchRealtime'
export function useSceneValues(
  project: string,
  models: SceneModel[],
  generation: number,
  paused = false
): Record<string, Record<string, number>> {
  const realtime = useBenchRealtimeData(project)
  const streamReady =
    !!realtime?.ready &&
    models
      .flatMap((m) => m.bindings)
      .every((b) => realtime.devices.some((d) => d.device_id === b.device_id))
  const [values, setValues] = useState<Record<string, Record<string, number>>>({})
  useEffect(() => {
    if (paused || streamReady || realtime?.blocked) return
    let live = true,
      inFlight = false
    const ids = [
      ...new Set(
        models.filter((m) => m.source_current).flatMap((m) => m.bindings.map((b) => b.device_id))
      )
    ]
    async function poll(): Promise<void> {
      if (inFlight) return
      inFlight = true
      try {
        const devices: BenchDeviceRecent[] = []
        for (let offset = 0; offset < ids.length; offset += 16) {
          devices.push(
            ...(await getBenchDeviceRecent(project, ids.slice(offset, offset + 16), { limit: 1 }))
          )
          if (!live || generation !== workspaceSessionGeneration()) return
        }
        if (!live || generation !== workspaceSessionGeneration()) return
        const next = valuesForModels(models, devices)
        setValues(next)
      } catch {
        if (live) setValues({})
      } finally {
        inFlight = false
      }
    }
    void poll()
    const timer = setInterval(() => void poll(), 2500)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [project, models, generation, paused, streamReady, realtime?.blocked])
  if (realtime?.blocked) return {}
  return !paused && streamReady && realtime ? valuesForModels(models, realtime.devices) : values
}

function valuesForModels(
  models: SceneModel[],
  devices: BenchDeviceRecent[]
): Record<string, Record<string, number>> {
  const next: Record<string, Record<string, number>> = {}
  for (const model of models) {
    next[model.id] = {}
    for (const binding of model.bindings) {
      const point = devices
        .find((d) => d.device_id === binding.device_id)
        ?.signals.find((s) => s.signal === binding.signal)
        ?.points.at(-1)
      const value = jointValue(binding, point, model.source_current, Date.now())
      if (value !== null) next[model.id][binding.joint] = value
    }
  }
  return next
}
