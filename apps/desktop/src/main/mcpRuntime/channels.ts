// SOLUSDEV-329 — desktop IPC for the MCP fork runtime
// (docs/architecture/mcp-fork-runtime.md §9). Channel names and the shapes
// shared by main, preload and the renderer; no runtime dependencies so the
// preload and renderer can import it.
import type { Candidate, ForkStatus, RuntimeErrorCode, RuntimeEvent } from './protocol'

export const MCP_RUNTIME_CHANNELS = {
  detect: 'mcpRuntime:detect',
  status: 'mcpRuntime:status',
  getChoice: 'mcpRuntime:getChoice',
  choose: 'mcpRuntime:choose',
  provision: 'mcpRuntime:provision',
  installManaged: 'mcpRuntime:installManaged',
  cancel: 'mcpRuntime:cancel',
  progress: 'mcpRuntime:progress'
} as const

// `first_run` is reserved for a future first-run prompt: the API accepts it,
// but nothing in the desktop sends it yet.
export const PROVISION_TRIGGERS = ['settings', 'first_run', 'repair'] as const
export type ProvisionTrigger = (typeof PROVISION_TRIGGERS)[number]

export type RuntimeMode = 'auto' | 'path' | 'managed'

export interface ChoiceView {
  mode: RuntimeMode
  path: string | null
  writable: boolean
}

/** `version_minor` is additive to §9 (`{ ok: true }`): the renderer needs it for
 *  `python_tools.interpreter_chosen` when the pick came from main's picker. */
export type ChooseResult =
  | { ok: true; version_minor: '3.12' | '3.13' | null }
  | { ok: false; error_code: RuntimeErrorCode }

/** `runId: null` ⇒ the user cancelled main's own download confirmation. */
export type InstallManagedResult = { runId: string } | { runId: null; error_code: 'cancelled' }

export interface ProgressPush {
  runId: string
  event: RuntimeEvent
}

export interface McpRuntimeBridge {
  detect(): Promise<{ candidates: Candidate[] }>
  status(): Promise<{ forks: ForkStatus[] }>
  getChoice(): Promise<ChoiceView>
  /** `{ mode: 'path' }` without a path opens main's file picker. */
  choose(request: { mode: RuntimeMode; path?: string }): Promise<ChooseResult>
  provision(request: { trigger: ProvisionTrigger; forks?: string[] }): Promise<{ runId: string }>
  installManaged(request: { consent: true }): Promise<InstallManagedResult>
  cancel(request: { runId: string }): Promise<{ ok: boolean }>
  onProgress(handler: (push: ProgressPush) => void): () => void
}

export type { Candidate, ForkStatus, RuntimeErrorCode, RuntimeEvent }
