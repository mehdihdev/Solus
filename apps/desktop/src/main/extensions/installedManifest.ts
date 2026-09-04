// SOLUSDEV-235 / EXT-05 — the manifest of an INSTALLED extension, read back
// from where it is served (the cached bundle, or the dev folder) so main-side
// decisions — which origins the network proxy may reach — are bounded by what
// the bundle actually declares, not by what a renderer says it declares.
import { EXTENSION_MANIFEST_FILENAME, type ExtensionManifest } from '@solus/shared-types'
import { join } from 'node:path'
import { safeDevFolder } from './devExtensions'
import type { ExtensionFs } from './extensionFs'
import { readExtensionIndex, type InstalledExtension } from './extensionIndex'
import { bundleDir, extensionsRoot } from './extensionPaths'
import { loadManifestFromBytes, MAX_MANIFEST_BYTES } from './manifestToml'

function servedRoot(id: string, entry: InstalledExtension, fs: ExtensionFs): string | null {
  if (entry.source === 'dev') return safeDevFolder(entry.devPath, fs)
  return bundleDir(extensionsRoot(fs.homedir()), id, entry.version)
}

/** The installed manifest for `id`, or null when absent/unreadable/invalid. */
export function readInstalledManifest(id: string, fs: ExtensionFs): ExtensionManifest | null {
  const entry = readExtensionIndex(fs).index.installed[id]
  if (entry === undefined) return null
  const root = servedRoot(id, entry, fs)
  if (root === null) return null
  const path = join(root, EXTENSION_MANIFEST_FILENAME)
  const size = fs.fileSize(path)
  if (size === null || size > MAX_MANIFEST_BYTES) return null
  try {
    const loaded = loadManifestFromBytes(fs.readFile(path))
    return loaded.ok && loaded.manifest.extension.id === id ? loaded.manifest : null
  } catch {
    return null
  }
}
