// SOLUSDEV-326 P3: the shell's one copy of the plugged-in device rows. The shell subscribes
// once (useDeviceStream) and the Hardware page reads from here, so opening the page never
// opens a second subscription. Rows are the reader's own view (docs/api/hardware.md
// "Device memory and Not now") and belong to one project: a switch or a sign-out resets them.
import { create } from 'zustand'
import type { DetectedDeviceOut, DeviceInspectionState } from '../../lib/api/hardware'

interface DeviceState {
  /** The project the rows belong to; null until the first rows of a project land. */
  projectId: string | null
  devices: readonly DetectedDeviceOut[]
  /** The remembered rows that left while watched, `last_seen` the moment each left: the
   *  machine's memory as last read is older than that. A row with no `last_seen` is a reader
   *  the memory does not reach, and is not kept. */
  left: readonly DetectedDeviceOut[]
  /** The refs SOL is owed a plug-in notice for, also when it was told before (`announced`): what
   *  the toast stood in for while the Hardware page was closed, what "+ Add hardware" asks about
   *  again, and a notice the page closed on inside its 2 s. A ref leaves when it stops being an
   *  offer; the open page takes the rest (usePlugInNotice). */
  unannounced: readonly string[]
  owe: (deviceRefs: readonly string[]) => void
  /** The page took what was owed. */
  settle: () => void
  setDevices: (projectId: string, devices: readonly DetectedDeviceOut[]) => void
  reset: () => void
}

const INITIAL = {
  projectId: null as string | null,
  devices: [] as readonly DetectedDeviceOut[],
  left: [] as readonly DetectedDeviceOut[],
  unannounced: [] as readonly string[]
}

function leftNow(
  was: Pick<DeviceState, 'devices' | 'left'>,
  devices: readonly DetectedDeviceOut[]
): DetectedDeviceOut[] {
  const present = new Set(devices.map((row) => row.device_ref))
  const at = new Date().toISOString()
  const gone = was.devices
    .filter((row) => row.device_ref && row.last_seen && !present.has(row.device_ref))
    .map((row) => ({ ...row, last_seen: at }))
  const again = new Set([...present, ...gone.map((row) => row.device_ref)])
  return [...gone, ...was.left.filter((row) => !again.has(row.device_ref))]
}

/** The offers SOL was told about in this app session (usePlugInNotice adds them), so that opening
 *  the Hardware page again announces none twice. It lives as long as the rows do: a sign-out or
 *  a project switch empties it, and a ref leaves when it stops being an offer (plugged in again,
 *  it is a new arrival).
 *  ponytail: a module set beside the store, not state: nothing renders from it, and the reader
 *  that fills it runs inside the store's own notification. */
export const announced = new Set<string>()

export const useDeviceStore = create<DeviceState>((set) => ({
  ...INITIAL,
  setDevices: (projectId, devices) =>
    set((was) => {
      const same = was.projectId === projectId
      const kept = same ? stillOffered([...announced], devices) : []
      announced.clear()
      for (const ref of kept) announced.add(ref)
      return {
        projectId,
        devices,
        left: same ? leftNow(was, devices) : [],
        unannounced: same ? stillOffered(was.unannounced, devices) : []
      }
    }),
  owe: (deviceRefs) =>
    set((was) => ({ unannounced: [...new Set([...was.unannounced, ...deviceRefs])] })),
  settle: () => set((was) => (was.unannounced.length ? { unannounced: [] } : was)),
  reset: () => {
    announced.clear()
    set({ ...INITIAL })
  }
}))

/** The inspection is over: there is something to show, or an honest "busy" / "unknown". */
const SETTLED: readonly DeviceInspectionState[] = ['inspected', 'busy', 'unknown']

/** A row SOL would offer: identified by a ref, held by nothing the reader may see, not waved
 *  off with "Not now", and inspected for this reader. Frame rows are narrowed only on their
 *  required fields, so every annotation is read defensively. */
export function isOffer(row: DetectedDeviceOut): boolean {
  return (
    row.device_ref !== null &&
    !row.bound_to &&
    row.dismissed !== true &&
    SETTLED.includes(row.state as DeviceInspectionState)
  )
}

function stillOffered(
  refs: readonly string[],
  devices: readonly DetectedDeviceOut[]
): readonly string[] {
  if (refs.length === 0) return refs
  const offered = new Set(devices.filter(isOffer).map((row) => row.device_ref))
  return refs.filter((ref) => offered.has(ref))
}

/** The rows of `next` that became an offer since `previous`: newly plugged in, or just settled. */
export function arrivedDevices(
  previous: readonly DetectedDeviceOut[],
  next: readonly DetectedDeviceOut[]
): DetectedDeviceOut[] {
  const before = new Set(previous.filter(isOffer).map((row) => row.device_ref))
  return next.filter((row) => isOffer(row) && !before.has(row.device_ref))
}
