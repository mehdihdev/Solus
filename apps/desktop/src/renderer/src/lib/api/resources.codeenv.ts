// SOLUSDEV-250 (INTEGRATIONS I3) — the Code environment route's typed client
// (docs/api/code-environment.md §2). This machine's linked folder plus the
// interpreter and virtual environment that run it: `probe` is a LIVE
// `code.probe_environment` over the caller's own bridge session (null when the
// companion is offline or the code server is not ready); `requirements`,
// `conflicts` and `proposal` come from the graph and are pure. The route never
// answers 409 — an offline bridge is `probe: null` with `bridge.connected` false.
import { api, type ApiClient } from './client'
import type { Source } from './resources'

export interface Interpreter {
  path: string
  version: string
}

export interface VenvPackage {
  name: string
  version: string
}

export interface VenvProbe {
  path: string
  python_version: string
  /** ≤300 entries; `truncated` says the list was cut. */
  packages: VenvPackage[]
  truncated: boolean
}

export interface CodeProbe {
  python: Interpreter | null
  interpreters: Interpreter[]
  venv: VenvProbe | null
  conda: { path: string; envs: string[] } | null
  uv: Interpreter | null
}

export interface CodeEnvironmentBridge {
  connected: boolean
  /** The Solus-authored `code` server is launched and answering. */
  code_server: boolean
}

export interface CodeRequirements {
  count: number
  /** Folder-relative source files (`isaac/requirements.txt`). */
  files: string[]
}

export type WarningSeverity = 'info' | 'warning' | 'critical'

/** The checker contract's Warning, on the wire. */
export interface CheckerWarning {
  checker_id: string
  severity: WarningSeverity
  message: string
  evidence: Record<string, unknown>
  suggested_area: string | null
}

export interface ProposedRequirement {
  name: string
  specifier: string
  source_file: string
}

export interface ProposedEnvironment {
  name: string
  source_files: string[]
  requirements: ProposedRequirement[]
}

/** `code.resolve_environment`'s answer (§5): one environment per conflicting
 *  source file when `split`, otherwise a single `default`. */
export interface EnvironmentProposal {
  environments: ProposedEnvironment[]
  split: boolean
}

export interface CodeEnvironmentView {
  source: Source | null
  bridge: CodeEnvironmentBridge
  probe: CodeProbe | null
  requirements: CodeRequirements
  conflicts: CheckerWarning[]
  proposal: EnvironmentProposal | null
}

export const EMPTY_CODE_ENVIRONMENT_VIEW: CodeEnvironmentView = {
  source: null,
  bridge: { connected: false, code_server: false },
  probe: null,
  requirements: { count: 0, files: [] },
  conflicts: [],
  proposal: null
}

const seg = encodeURIComponent

/** This machine's Code environment for the project. Absent fields are widened
 *  to the empty view so callers never branch on a missing key. */
export async function getCodeEnvironment(
  projectId: string,
  machineId: string,
  client: ApiClient = api
): Promise<CodeEnvironmentView> {
  const raw = await client.request<Partial<CodeEnvironmentView>>(
    `/projects/${seg(projectId)}/code-environment?machine_id=${seg(machineId)}`
  )
  return {
    source: raw.source ?? null,
    bridge: raw.bridge ?? EMPTY_CODE_ENVIRONMENT_VIEW.bridge,
    probe: raw.probe ?? null,
    requirements: raw.requirements ?? EMPTY_CODE_ENVIRONMENT_VIEW.requirements,
    conflicts: raw.conflicts ?? [],
    proposal: raw.proposal ?? null
  }
}
