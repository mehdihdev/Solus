// SOLUSDEV-329 — mcpRuntime:* IPC (docs/architecture/mcp-fork-runtime.md §9).
//
// Every channel is sender-gated to the app's own renderer and treats its
// input as untrusted. At most one provision / install-managed run exists at a
// time; its progress goes to the webContents that started it, and only to
// it. A provision whose `done` reports ok > 0 respawns the companion so the
// newly trusted forks launch. Decisions live here with injected deps; main's
// index.ts binds the real ones.
import {
  MCP_RUNTIME_CHANNELS,
  PROVISION_TRIGGERS,
  type ChooseResult,
  type ChoiceView,
  type InstallManagedResult,
  type ProvisionTrigger
} from './channels'
import { isForkName, type Candidate, type ForkStatus, type RuntimeEvent } from './protocol'
import {
  startRuntimeRun,
  runtimeArgv,
  type CommandLine,
  type RuntimeCommand,
  type RuntimeRun,
  type RuntimeRunDeps
} from './runtimeCli'
import { parseChoiceInput, type RuntimeChoice, type RuntimeSettings } from './runtimeSettings'
import type { ProbeResult } from './probe'

const READ_TIMEOUT_MS = 60_000
const PROVISION_TIMEOUT_MS = 60 * 60_000
const INSTALL_MANAGED_TIMEOUT_MS = 15 * 60_000
/** Comfortably above the six vendored forks; bounds the argv. */
const MAX_FORKS = 32
const RUN_ID_MAX = 64

/** The webContents an invoke came from — what progress is pushed back to. */
export interface IpcSender {
  send(channel: string, payload: unknown): void
  isDestroyed(): boolean
}
export interface IpcEvent {
  sender: IpcSender
}

export interface McpRuntimeIpcDeps {
  isAllowed(event: IpcEvent): boolean
  /** The companion's own command (resolveCompanionCommand); null ⇒ unavailable. */
  commandLine(): CommandLine | null
  env(): Record<string, string | undefined>
  run: RuntimeRunDeps
  settings: RuntimeSettings
  probe(path: string): Promise<ProbeResult>
  /** Main's file dialog; null when the user cancels. A user gesture, so its pick may be probed. */
  pickInterpreter(): Promise<string | null>
  /** Canonical path, or null when it does not exist. */
  realpath(path: string): string | null
  /** Main's own dialog naming the managed download and its size; true ⇒ go ahead. */
  confirmManagedDownload(): Promise<boolean>
  respawnCompanion(): void
  newRunId(): string
}

export interface McpRuntimeIpc {
  detect(event: IpcEvent): Promise<{ candidates: Candidate[] }>
  status(event: IpcEvent): Promise<{ forks: ForkStatus[] }>
  getChoice(event: IpcEvent): Promise<ChoiceView>
  choose(event: IpcEvent, input: unknown): Promise<ChooseResult>
  provision(event: IpcEvent, input: unknown): Promise<{ runId: string }>
  installManaged(event: IpcEvent, input: unknown): Promise<InstallManagedResult>
  cancel(event: IpcEvent, input: unknown): Promise<{ ok: boolean }>
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

interface ProvisionInput {
  trigger: ProvisionTrigger
  forks?: string[]
}

function parseProvisionInput(input: unknown): ProvisionInput | null {
  if (!isRecord(input)) return null
  const { trigger, forks } = input
  if (!(PROVISION_TRIGGERS as readonly unknown[]).includes(trigger)) return null
  if (forks === undefined) return { trigger: trigger as ProvisionTrigger }
  if (!Array.isArray(forks) || forks.length > MAX_FORKS || !forks.every(isForkName)) return null
  return { trigger: trigger as ProvisionTrigger, forks: [...new Set(forks)] }
}

const isConsent = (input: unknown): boolean =>
  isRecord(input) && input.consent === true && Object.keys(input).length === 1

export function createMcpRuntimeIpc(deps: McpRuntimeIpcDeps): McpRuntimeIpc {
  let active: { runId: string; run: RuntimeRun } | null = null
  /** Realpaths of the supported candidates from the latest detect: the only
   *  renderer-named paths main will ever execute (security MEDIUM-1). */
  let detected: ReadonlySet<string> = new Set()

  const gate = (event: IpcEvent): void => {
    if (!deps.isAllowed(event)) throw new Error('unauthorized sender')
  }

  const line = (cmd: RuntimeCommand): CommandLine => {
    const base = deps.commandLine()
    if (base === null) throw new Error('unavailable')
    return runtimeArgv(base, cmd)
  }

  /** A read-only command: collect its events and return them. */
  const collect = async (cmd: RuntimeCommand): Promise<RuntimeEvent[]> => {
    const events: RuntimeEvent[] = []
    const run = startRuntimeRun(line(cmd), deps.env(), {
      onEvent: (e) => events.push(e),
      timeoutMs: READ_TIMEOUT_MS,
      deps: deps.run
    })
    await run.result
    return events
  }

  /** A provisioning command: one at a time, progress to the requester. */
  const startTracked = (event: IpcEvent, cmd: RuntimeCommand, timeoutMs: number): string => {
    if (active !== null) throw new Error('busy')
    const cmdLine = line(cmd)
    const runId = deps.newRunId()
    const push = (e: RuntimeEvent): void => {
      if (!event.sender.isDestroyed()) {
        event.sender.send(MCP_RUNTIME_CHANNELS.progress, { runId, event: e })
      }
    }
    const run = startRuntimeRun(cmdLine, deps.env(), { onEvent: push, timeoutMs, deps: deps.run })
    active = { runId, run }
    void run.result.then(({ done }) => {
      if (active?.runId === runId) active = null
      if (cmd.command === 'provision' && done.ok > 0) deps.respawnCompanion()
    })
    return runId
  }

  const savedChoice = (): RuntimeChoice => {
    const view = deps.settings.read()
    return view.mode === 'path' && view.path !== null
      ? { mode: 'path', path: view.path }
      : { mode: view.mode === 'managed' ? 'managed' : 'auto', path: null }
  }

  const wasDetected = (path: string): boolean => {
    const real = deps.realpath(path)
    return real !== null && detected.has(real)
  }

  /** Resolve the path to save: a detected candidate's, or the picker's. */
  const choosePath = async (path: string | null): Promise<ChooseResult & { path?: string }> => {
    if (path !== null && !wasDetected(path)) return { ok: false, error_code: 'python_not_found' }
    const target = path ?? (await deps.pickInterpreter())
    if (target === null) return { ok: false, error_code: 'cancelled' }
    const probe = await deps.probe(target)
    return probe.ok ? { ok: true, version_minor: probe.minor, path: target } : probe
  }

  const choose = async (input: unknown): Promise<ChooseResult> => {
    const request = parseChoiceInput(input)
    if (request === null) return { ok: false, error_code: 'internal' }
    if (!deps.settings.read().writable) return { ok: false, error_code: 'internal' }
    if (request.mode !== 'path') {
      if (!deps.settings.write({ mode: request.mode, path: null })) {
        return { ok: false, error_code: 'internal' }
      }
      return { ok: true, version_minor: request.mode === 'managed' ? '3.12' : null }
    }
    const resolved = await choosePath(request.path)
    if (!resolved.ok || resolved.path === undefined) return resolved
    if (!deps.settings.write({ mode: 'path', path: resolved.path })) {
      return { ok: false, error_code: 'internal' }
    }
    return { ok: true, version_minor: resolved.version_minor }
  }

  return {
    async detect(event) {
      gate(event)
      const events = await collect({ command: 'detect' })
      const candidates = events.filter((e): e is Candidate => e.type === 'candidate')
      detected = new Set(
        candidates
          .filter((c) => c.supported)
          .map((c) => deps.realpath(c.path))
          .filter((real): real is string => real !== null)
      )
      return { candidates }
    },
    async status(event) {
      gate(event)
      const events = await collect({ command: 'status' })
      return { forks: events.filter((e): e is ForkStatus => e.type === 'status') }
    },
    async getChoice(event) {
      gate(event)
      return deps.settings.read()
    },
    async choose(event, input) {
      gate(event)
      return choose(input)
    },
    async provision(event, input) {
      gate(event)
      const request = parseProvisionInput(input)
      if (request === null) throw new Error('invalid request')
      const cmd: RuntimeCommand = {
        command: 'provision',
        forks: request.forks,
        python: savedChoice()
      }
      return { runId: startTracked(event, cmd, PROVISION_TIMEOUT_MS) }
    },
    async installManaged(event, input) {
      gate(event)
      if (!isConsent(input)) throw new Error('consent required')
      // The renderer's consent alone is not enough (security LOW-3).
      const confirmed = await deps.confirmManagedDownload().catch(() => false)
      if (!confirmed) return { runId: null, error_code: 'cancelled' }
      return {
        runId: startTracked(event, { command: 'install-managed' }, INSTALL_MANAGED_TIMEOUT_MS)
      }
    },
    async cancel(event, input) {
      gate(event)
      const runId = isRecord(input) ? input.runId : undefined
      if (typeof runId !== 'string' || runId.length > RUN_ID_MAX) return { ok: false }
      if (active === null || active.runId !== runId) return { ok: false }
      active.run.cancel()
      return { ok: true }
    }
  }
}

/** Structural slice of ipcMain. */
export interface IpcMainLike {
  handle(channel: string, listener: (event: IpcEvent, input: unknown) => unknown): void
}

export function registerMcpRuntimeIpc(ipcMain: IpcMainLike, ipc: McpRuntimeIpc): void {
  const c = MCP_RUNTIME_CHANNELS
  ipcMain.handle(c.detect, (event) => ipc.detect(event))
  ipcMain.handle(c.status, (event) => ipc.status(event))
  ipcMain.handle(c.getChoice, (event) => ipc.getChoice(event))
  ipcMain.handle(c.choose, (event, input) => ipc.choose(event, input))
  ipcMain.handle(c.provision, (event, input) => ipc.provision(event, input))
  ipcMain.handle(c.installManaged, (event, input) => ipc.installManaged(event, input))
  ipcMain.handle(c.cancel, (event, input) => ipc.cancel(event, input))
}
