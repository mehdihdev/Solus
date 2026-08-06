// SOLUSDEV-216 (CTR-01) — the glob-based discovery loader.
//
// This is the ONLY place the widget set is assembled, and it names no widget.
// Adding a widget is creating a directory with a `widget.manifest.ts` in it —
// no shared file to edit, so no file for six lanes to conflict on.
//
// `import.meta.glob` is a Vite transform, which is why it lives here and not in
// @solus/shared-types: the contract stays framework-free and unit-testable, and
// only this one line is bundler-bound.
import { collectManifests, type WidgetManifest } from '@solus/shared-types'

const MODULES = import.meta.glob('./*/widget.manifest.ts', { eager: true })

/**
 * Every widget in this build, validated and id-sorted.
 *
 * THROWS if a manifest is malformed or two widgets claim the same id, naming
 * the offending file. That is deliberate: these are in-repo build-time errors,
 * and a loader that skipped a broken widget would ship a workspace with one
 * mysteriously missing and no way to tell why.
 */
export function discoverWidgets(): WidgetManifest[] {
  return collectManifests(MODULES)
}
