// SOLUSDEV-216 (CTR-01) — how a widget declares itself.
//
// THIS FILE IS THE WHOLE REGISTRATION. There is no central registry to edit, no
// switch statement to extend, no array in a shared module to append to — which
// is why six lanes can each add a widget without ever touching the same file.
// The canvas finds this manifest by glob (see ../discover.ts).
//
// Copy this shape into `<your-widget>/widget.manifest.ts`. Default export, or
// discovery throws and names your file.
import type { WidgetManifest } from '@solus/shared-types'
import { ReferenceWidget } from './ReferenceWidget'

const manifest: WidgetManifest = {
  /** Stable slug, unique across every lane. It ends up in saved layouts. */
  id: 'reference',
  title: 'Reference',
  /** Empty means "relevant in every domain". Narrow it if yours is not. */
  domains: [],
  size: { preferred: 'compact', minimum: 'compact' },
  component: ReferenceWidget
  // lifecycle is optional — React's useEffect cleanup covers the ordinary case.
  // Define it only for a resource that must outlive a render (a socket, a window).
}

export default manifest
