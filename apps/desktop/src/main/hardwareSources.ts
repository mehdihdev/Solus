// Authenticated native picker authority for ADR-034 private hardware sources.
// Renderer requests never carry account IDs or filesystem paths.
import { createHash, randomUUID } from 'node:crypto'
import { constants, type Stats } from 'node:fs'
import { lstat, open, realpath, type FileHandle } from 'node:fs/promises'
import { extname, isAbsolute, resolve } from 'node:path'
import type { HardwareLocalAccount, HardwareLocalSource } from '@solus/shared-types'
import { HARDWARE_UUID, HardwareLocalStore } from './hardwareLocalState'

export const MAX_HARDWARE_SOURCE_BYTES = 256 * 1024
const MAX_AUTH_BYTES = 256 * 1024
const AUTH_TIMEOUT_MS = 8_000
const EXTENSIONS = new Set(['.json', '.yaml', '.yml', '.toml', '.py'])

export type HardwareSourceFailure =
  | 'unauthorized'
  | 'invalid'
  | 'newer'
  | 'unavailable'
  | 'stale_scope'
  | 'not_found'
  | 'cancelled'
  | 'busy'
  | 'source_changed'
  | 'relink_required'
export type HardwareSourceResult<T> =
  | { ok: true; value: T }
  | { ok: false; reason: HardwareSourceFailure }
export interface HardwareSourceReference {
  sourceRef: string
  contentSha256: string
  displayName: string
}
export interface HardwareSourceScope {
  projectId: string
  accountId: string
}
export interface HardwareSourceList extends HardwareSourceScope {
  sources: HardwareSourceReference[]
}
export interface HardwareSourcePicked extends HardwareSourceScope {
  source: HardwareSourceReference
}
export interface HardwareSourcePickInput {
  sourceRef?: string
}
export interface DigestChange {
  displayName: string
  previousDigest: string
  contentSha256: string
}
export interface SelectedHardwareFile {
  canonicalPath: string
  bytes: Uint8Array
}
export interface HardwareSourcesDeps {
  store: HardwareLocalStore
  authorize: (token: string, projectId: string, signal: AbortSignal) => Promise<string | null>
  pickFile: () => Promise<string | null>
  confirmDigestChange: (change: DigestChange) => Promise<boolean>
  readFile: (path: string) => Promise<SelectedHardwareFile>
  newId?: () => string
}
interface Scope extends HardwareSourceScope {
  generation: number
  token: string
  signal: AbortSignal
}

function fail(reason: HardwareSourceFailure): { ok: false; reason: HardwareSourceFailure } {
  return { ok: false, reason }
}
function sourceInput(raw: unknown, required: boolean): HardwareSourcePickInput | null {
  if (
    raw === null ||
    typeof raw !== 'object' ||
    Array.isArray(raw) ||
    Object.keys(raw).some((key) => key !== 'sourceRef')
  )
    return null
  const ref = (raw as Record<string, unknown>).sourceRef
  if (ref === undefined) return required ? null : {}
  return typeof ref === 'string' && HARDWARE_UUID.test(ref) ? { sourceRef: ref } : null
}
function reference(sourceRef: string, source: HardwareLocalSource): HardwareSourceReference {
  // Only a portable filename leaves MAIN, never a native parent directory.
  const displayName = (source.path.split(/[\\/]/u).pop() ?? '')
    // Strip terminal/control bytes before exposing the filename to the renderer.
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f-\u009f]/gu, '')
    .slice(0, 256)
  return { sourceRef, contentSha256: source.contentSha256, displayName }
}

export class HardwareSources {
  private token: string | null = null
  private projectId: string | null = null
  private generation = 0
  private abort = new AbortController()
  private picking = false

  constructor(private readonly deps: HardwareSourcesDeps) {}

  setToken(token: string | null): void {
    const next =
      token !== null && token.length > 0 && token.length <= 16_384 && !/[\r\n]/u.test(token)
        ? token
        : null
    if (next !== this.token) {
      this.token = next
      this.invalidate()
    }
  }
  setProject(projectId: string | null): void {
    const next = projectId !== null && HARDWARE_UUID.test(projectId) ? projectId : null
    if (next !== this.projectId) {
      this.projectId = next
      this.invalidate()
    }
  }
  invalidate(): void {
    this.generation += 1
    this.abort.abort()
    this.abort = new AbortController()
  }
  private current(scope: Scope): boolean {
    return scope.generation === this.generation && !scope.signal.aborted
  }
  private async scope(senderOk: boolean): Promise<HardwareSourceResult<Scope>> {
    if (!senderOk || this.token === null || this.projectId === null) return fail('unauthorized')
    const generation = this.generation
    const token = this.token
    const projectId = this.projectId
    const signal = this.abort.signal
    let accountId: string | null
    try {
      accountId = await this.deps.authorize(token, projectId, signal)
    } catch {
      accountId = null
    }
    if (generation !== this.generation || signal.aborted) return fail('stale_scope')
    if (accountId === null || !HARDWARE_UUID.test(accountId)) return fail('unauthorized')
    return { ok: true, value: { generation, token, projectId, accountId, signal } }
  }
  private account(scope: Scope): HardwareSourceResult<HardwareLocalAccount> {
    if (!this.current(scope)) return fail('stale_scope')
    const read = this.deps.store.read(scope.projectId)
    return read.status === 'ready'
      ? { ok: true, value: read.state.accounts[scope.accountId] ?? { sources: {}, bindings: {} } }
      : fail(read.status)
  }

  async list(senderOk: boolean): Promise<HardwareSourceResult<HardwareSourceList>> {
    const auth = await this.scope(senderOk)
    if (!auth.ok) return auth
    const account = this.account(auth.value)
    if (!account.ok) return account
    return {
      ok: true,
      value: {
        projectId: auth.value.projectId,
        accountId: auth.value.accountId,
        sources: Object.entries(account.value.sources).map(([id, source]) => reference(id, source))
      }
    }
  }

  async pick(senderOk: boolean, raw: unknown): Promise<HardwareSourceResult<HardwareSourcePicked>> {
    if (!senderOk) return fail('unauthorized')
    const input = sourceInput(raw, false)
    if (input === null) return fail('invalid')
    if (this.picking) return fail('busy')
    this.picking = true
    try {
      const auth = await this.scope(senderOk)
      if (!auth.ok) return auth
      return await this.pickAuthorized(auth.value, input)
    } catch {
      return fail('unavailable')
    } finally {
      this.picking = false
    }
  }

  private async selectFile(scope: Scope): Promise<HardwareSourceResult<SelectedHardwareFile>> {
    const path = await this.deps.pickFile()
    if (!this.current(scope)) return fail('stale_scope')
    if (path === null) return fail('cancelled')
    try {
      const file = await this.deps.readFile(path)
      return this.current(scope) ? { ok: true, value: file } : fail('stale_scope')
    } catch {
      return this.current(scope) ? fail('relink_required') : fail('stale_scope')
    }
  }

  private async confirmReplacement(
    scope: Scope,
    previous: HardwareLocalSource | undefined,
    portable: HardwareSourceReference
  ): Promise<HardwareSourceResult<void>> {
    if (previous !== undefined && previous.contentSha256 !== portable.contentSha256) {
      const accepted = await this.deps.confirmDigestChange({
        displayName: portable.displayName,
        previousDigest: previous.contentSha256,
        contentSha256: portable.contentSha256
      })
      if (!this.current(scope)) return fail('stale_scope')
      if (!accepted) return fail('cancelled')
    }
    return { ok: true, value: undefined }
  }

  private async pickAuthorized(
    scope: Scope,
    input: HardwareSourcePickInput
  ): Promise<HardwareSourceResult<HardwareSourcePicked>> {
    const account = this.account(scope)
    if (!account.ok) return account
    const selected = await this.selectFile(scope)
    if (!selected.ok) return selected
    const file = selected.value
    const source = {
      path: file.canonicalPath,
      contentSha256: createHash('sha256').update(file.bytes).digest('hex')
    }
    const existing = Object.entries(account.value.sources).find(
      ([, saved]) => saved.path === file.canonicalPath
    )
    const sourceRef = input.sourceRef ?? existing?.[0] ?? (this.deps.newId ?? randomUUID)()
    const previous = account.value.sources[sourceRef] ?? existing?.[1]
    const portable = reference(sourceRef, source)
    const accepted = await this.confirmReplacement(scope, previous, portable)
    if (!accepted.ok) return accepted
    return this.saveSource(scope, sourceRef, source, portable)
  }

  private async saveSource(
    scope: Scope,
    sourceRef: string,
    source: HardwareLocalSource,
    portable: HardwareSourceReference
  ): Promise<HardwareSourceResult<HardwareSourcePicked>> {
    // Membership can be revoked while a native dialog is open. Revalidate it.
    const verified = await this.deps.authorize(scope.token, scope.projectId, scope.signal)
    if (!this.current(scope)) return fail('stale_scope')
    if (verified !== scope.accountId) return fail('unauthorized')
    const written = this.deps.store.updateAccount(scope.projectId, scope.accountId, (latest) => ({
      ...latest,
      sources: { ...latest.sources, [sourceRef]: source }
    }))
    return written.ok
      ? {
          ok: true,
          value: {
            projectId: scope.projectId,
            accountId: scope.accountId,
            source: portable
          }
        }
      : fail(written.reason)
  }

  async recheck(
    senderOk: boolean,
    raw: unknown
  ): Promise<HardwareSourceResult<HardwareSourcePicked>> {
    if (!senderOk) return fail('unauthorized')
    const input = sourceInput(raw, true)
    if (input?.sourceRef === undefined) return fail('invalid')
    const auth = await this.scope(senderOk)
    if (!auth.ok) return auth
    const scope = auth.value
    const account = this.account(scope)
    if (!account.ok) return account
    const source = account.value.sources[input.sourceRef]
    if (source === undefined) return fail('not_found')
    return this.recheckSource(scope, input.sourceRef, source)
  }

  private async recheckSource(
    scope: Scope,
    sourceRef: string,
    source: HardwareLocalSource
  ): Promise<HardwareSourceResult<HardwareSourcePicked>> {
    try {
      const selected = await this.deps.readFile(source.path)
      if (!this.current(scope)) return fail('stale_scope')
      const actual = createHash('sha256').update(selected.bytes).digest('hex')
      if (actual !== source.contentSha256) return fail('source_changed')
      return {
        ok: true,
        value: {
          projectId: scope.projectId,
          accountId: scope.accountId,
          source: reference(sourceRef, source)
        }
      }
    } catch {
      return this.current(scope) ? fail('relink_required') : fail('stale_scope')
    }
  }
}

function validateSourcePath(path: string): void {
  if (
    !isAbsolute(path) ||
    path.length > 4096 ||
    // Reject control bytes at the local filesystem boundary.
    // eslint-disable-next-line no-control-regex
    /[\u0000-\u001f\u007f-\u009f]/u.test(path) ||
    !EXTENSIONS.has(extname(path).toLowerCase())
  )
    throw new Error('invalid hardware source')
}

function sameFile(before: Stats, after: Stats): boolean {
  return (
    after.isFile() &&
    after.ino === before.ino &&
    after.dev === before.dev &&
    after.size === before.size &&
    after.mtimeMs === before.mtimeMs
  )
}

async function readSourceBytes(handle: FileHandle): Promise<Buffer> {
  const buffer = Buffer.alloc(MAX_HARDWARE_SOURCE_BYTES + 1)
  let size = 0
  while (size < buffer.length) {
    const { bytesRead } = await handle.read(buffer, size, buffer.length - size, null)
    if (!bytesRead) break
    size += bytesRead
  }
  return buffer.subarray(0, size)
}

/** Bounded regular UTF-8 configuration files only; parsing happens in the plugin.
 * Reject symlinks and canonical-path changes both before and after the open. */
export async function readHardwareSource(path: string): Promise<SelectedHardwareFile> {
  validateSourcePath(path)
  const canonicalPath = await realpath(path)
  if (canonicalPath !== resolve(path)) throw new Error('source path changed')
  const handle = await open(
    canonicalPath,
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK
  )
  try {
    const before = await handle.stat()
    if (!before.isFile() || before.size > MAX_HARDWARE_SOURCE_BYTES)
      throw new Error('invalid source size')
    const bytes = await readSourceBytes(handle)
    const after = await lstat(canonicalPath)
    if (
      bytes.length > MAX_HARDWARE_SOURCE_BYTES ||
      !sameFile(before, after) ||
      (await realpath(path)) !== canonicalPath
    )
      throw new Error('source changed during read')
    new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return { canonicalPath, bytes }
  } finally {
    await handle.close()
  }
}

async function apiId(response: Response): Promise<string | null> {
  if (!response.ok || response.body === null) return null
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_AUTH_BYTES) return null
      chunks.push(value)
    }
    return parsedApiId(JSON.parse(Buffer.concat(chunks).toString('utf8')))
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

function parsedApiId(value: unknown): string | null {
  if (value === null || typeof value !== 'object' || !('data' in value)) return null
  const data = value.data
  return data !== null &&
    typeof data === 'object' &&
    'id' in data &&
    typeof data.id === 'string' &&
    HARDWARE_UUID.test(data.id)
    ? data.id
    : null
}

function authorizedBase(base: URL): boolean {
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)
  return (
    !base.username &&
    !base.password &&
    !base.search &&
    !base.hash &&
    (base.protocol === 'https:' || (base.protocol === 'http:' && loopback))
  )
}

/** Never decode renderer claims as authorization. Ask the configured API using
 * the already-relayed bearer token; it verifies identity and project membership. */
export async function authorizeHardwareScope(
  token: string,
  projectId: string,
  signal: AbortSignal,
  apiBaseUrl: string,
  fetcher: typeof globalThis.fetch = globalThis.fetch
): Promise<string | null> {
  if (!HARDWARE_UUID.test(projectId) || signal.aborted) return null
  try {
    const base = new URL(apiBaseUrl)
    if (!authorizedBase(base)) return null
    const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(AUTH_TIMEOUT_MS)])
    const options: RequestInit = {
      headers: { Authorization: `Bearer ${token}` },
      redirect: 'error',
      signal: requestSignal
    }
    const root = base.toString().replace(/\/$/u, '')
    const accountId = await apiId(await fetcher(`${root}/users/me`, options))
    if (accountId === null) return null
    const verifiedProjectId = await apiId(await fetcher(`${root}/projects/${projectId}`, options))
    return verifiedProjectId === projectId && !requestSignal.aborted ? accountId : null
  } catch {
    return null
  }
}
