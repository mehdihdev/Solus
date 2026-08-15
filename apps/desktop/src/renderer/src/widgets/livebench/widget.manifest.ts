// SOLUSDEV-66 (LB-05) — the Live Bench widget's self-registration.
// Discovery is the glob in widgets/discover.ts; adding this file IS the wiring —
// no shared file is edited (CTR-01).
import type { WidgetManifest } from '@solus/shared-types'
import { LiveBenchWidget } from './LiveBenchWidget'

const manifest: WidgetManifest = {
  id: 'livebench',
  title: 'Live Bench',
  domains: ['simulation', 'runtime'],
  size: { preferred: 'wide', minimum: 'standard' },
  component: LiveBenchWidget
}

export default manifest
