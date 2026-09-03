// SOLUSDEV-235 / EXT-05 — extension.toml bytes → decoded TOML → the contract
// parser (parseExtensionManifest takes the DECODED object, never text, so the
// desktop and the publish validator read one shape). The file is untrusted
// developer input: capped in bytes before decoding, and every failure comes
// back as a dotted-path problem string the developer mode can show verbatim.
import { parseExtensionManifest, type ExtensionManifest } from '@solus/shared-types'
import { parse, TomlError } from 'smol-toml'

/** A manifest is a few hundred bytes; anything past this is not one. */
export const MAX_MANIFEST_BYTES = 64 * 1024

export type ManifestLoadResult =
  | { readonly ok: true; readonly manifest: ExtensionManifest }
  | {
      readonly ok: false
      readonly reason: 'invalid' | 'newer' | 'too_large'
      readonly problems: readonly string[]
    }

function invalid(problem: string): ManifestLoadResult {
  return { ok: false, reason: 'invalid', problems: [problem] }
}

function describeTomlError(error: unknown): string {
  if (error instanceof TomlError)
    return `line ${error.line}, column ${error.column}: ${error.message}`
  return error instanceof Error ? error.message : 'unparseable TOML'
}

export function loadManifestFromBytes(bytes: Uint8Array): ManifestLoadResult {
  if (bytes.byteLength > MAX_MANIFEST_BYTES)
    return {
      ok: false,
      reason: 'too_large',
      problems: [`extension.toml: exceeds ${MAX_MANIFEST_BYTES} bytes`]
    }
  let text: string
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    return invalid('extension.toml: not valid UTF-8')
  }
  let decoded: unknown
  try {
    decoded = parse(text)
  } catch (error) {
    return invalid(`extension.toml: ${describeTomlError(error)}`)
  }
  const parsed = parseExtensionManifest(decoded)
  return parsed.ok ? parsed : { ok: false, reason: parsed.reason, problems: parsed.problems }
}
