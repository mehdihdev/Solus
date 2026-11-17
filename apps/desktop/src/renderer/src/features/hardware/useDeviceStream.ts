// SOLUSDEV-326 P3: the shell's one subscription to the project's plugged-in devices — the
// `hardware.devices_changed` frames plus one `GET /detected` seed — kept in deviceStore for the
// Hardware page. Away from that page, a device that arrives raises the plug-in toast, and the
// store remembers it: the page announces it to SOL when it opens (usePlugInNotice).
import { useCallback, useEffect, useRef } from 'react'
import { listDetectedDevices, type DetectedDeviceOut } from '../../lib/api/hardware'
import { useWorkspaceEvents } from '../graph/useWorkspaceEvents'
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { arrivedDevices, useDeviceStore } from './deviceStore'

/** Graph hints are the Workspace screen's business; this subscription only wants devices. */
const ignoreGraph = (): void => undefined

function loadedRows(projectId: string): readonly DetectedDeviceOut[] | null {
  const store = useDeviceStore.getState()
  return store.projectId === projectId ? store.devices : null
}

export function useDeviceStream(projectId: string | null, currentScreen: string): void {
  const enabled = useWorkspaceFetchEnabled()
  const screen = useRef(currentScreen)
  useEffect(() => {
    screen.current = currentScreen
  }, [currentScreen])

  const onDevices = useCallback(
    (devices: DetectedDeviceOut[]) => {
      if (!projectId) return
      // No rows yet means no baseline: what was plugged in before Solus looked is not an arrival.
      const before = loadedRows(projectId)
      useDeviceStore.getState().setDevices(projectId, devices)
      if (!before || screen.current === 'hardware') return
      const arrived = arrivedDevices(before, devices)
      if (arrived.length === 0) return
      useDeviceStore.getState().owe(arrived.map((row) => row.device_ref as string))
      useShellStore.getState().setToast({
        kind: 'ok',
        title: 'Something was plugged in',
        body: 'Open Hardware to see it.',
        action: 'Open Hardware',
        screen: 'hardware'
      })
    },
    [projectId]
  )
  useWorkspaceEvents(projectId, ignoreGraph, undefined, onDevices)

  useEffect(() => {
    if (!projectId || !enabled) return
    let current = true
    listDetectedDevices(projectId)
      .then((devices) => {
        // A frame is the authoritative full list: it supersedes a seed still in flight.
        if (current && loadedRows(projectId) === null)
          useDeviceStore.getState().setDevices(projectId, devices)
      })
      // ponytail: no error state — a hosted API or an unreachable one has no local devices to
      // list, and the frames still fill the rows. The Hardware page reports its own reads.
      .catch(() => undefined)
    return () => {
      current = false
      useDeviceStore.getState().reset()
    }
  }, [projectId, enabled])
}
