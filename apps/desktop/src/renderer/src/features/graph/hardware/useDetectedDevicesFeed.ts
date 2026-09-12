import { recordDeviceFrame } from '../../../lib/perf/marks'
import { useCallback, useEffect, useRef } from 'react'
import { listDetectedDevices, type DetectedDeviceOut } from '../../../lib/api/hardware'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { useDetectedDevicesStore } from './detectedDevicesStore'

/** A full SSE list outranks a pending GET; every scope transition expires old work. */
export function useDetectedDevicesFeed(projectId: string | null): {
  onDevices: (devices: DetectedDeviceOut[]) => void
  seed: () => void
} {
  const generation = useWorkspaceSessionGeneration()
  const current = useRef({ active: false, frame: 0, request: 0 })
  useEffect(() => {
    const scope = { active: true, frame: 0, request: 0 }
    current.current = scope
    recordDeviceFrame([])
    useDetectedDevicesStore.getState().reset()
    return () => {
      scope.active = false
    }
  }, [projectId, generation])
  const onDevices = useCallback(
    (devices: DetectedDeviceOut[]) => {
      if (!current.current.active || workspaceSessionGeneration() !== generation) return
      current.current.frame += 1
      recordDeviceFrame(devices.flatMap((device) => (device.device_ref ? [device.device_ref] : [])))
      useDetectedDevicesStore.getState().setDevices(devices)
    },
    [generation]
  )
  const seed = useCallback(() => {
    if (!projectId) return
    const scope = current.current
    const frame = scope.frame
    const request = ++scope.request
    listDetectedDevices(projectId).then(
      (devices) => {
        if (
          scope.active &&
          current.current === scope &&
          request === scope.request &&
          frame === scope.frame &&
          workspaceSessionGeneration() === generation
        )
          useDetectedDevicesStore.getState().setDevices(devices)
      },
      () => undefined
    )
  }, [projectId, generation])
  return { onDevices, seed }
}
