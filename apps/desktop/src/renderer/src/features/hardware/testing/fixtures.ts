// A plugged-in device row as `GET /detected` and the device frame carry it (docs/api/hardware.md).
import type { DetectedDeviceOut } from '../../../lib/api/hardware'

export const device = (ref: string, over: Partial<DetectedDeviceOut> = {}): DetectedDeviceOut => ({
  transport: 'usb_serial',
  device_ref: ref,
  identity: null,
  level: 'board',
  board: null,
  board_class: null,
  mcu_known: false,
  confidence: 0.5,
  evidence: [],
  ambiguous: false,
  last_seen_path: null,
  bound_to: null,
  dismissed: false,
  last_seen: null,
  state: 'inspected',
  ...over
})
