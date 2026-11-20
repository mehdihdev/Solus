// SOLUSDEV-329 — every string Settings › Python for local tools shows
// (docs/wireflows/settings.md). Copy follows the SOL mode (ADR-016): Guide
// says in one plain sentence what Python is for here and why the step is
// needed; Expert gives the state, the code and the action only.
import type { SolMode } from '../../../store/settingsStore'
import type { RuntimeErrorCode } from '../../../../../main/mcpRuntime/protocol'

export const SECTION_TITLE = 'Python for local tools'
export const MANAGED_DOWNLOAD_LABEL = 'Install Python for Solus (~30 MB download)'
export const NONE_FOUND = 'No Python 3.12 or 3.13 found.'
export const MANAGED_OPTION = 'Solus-managed Python 3.12'

type ByMode = Readonly<Record<SolMode, string>>

export const COPY = {
  intro: {
    Guide:
      'Local tools like KiCad and Code run on Python on this computer. Solus builds each tool its own private copy from the Python you pick, so your own Python setup never changes.',
    Expert: 'Base interpreter for local MCP tools: CPython 3.12 or 3.13.'
  },
  detecting: {
    Guide: 'Looking for Python on this computer…',
    Expert: 'Detecting interpreters…'
  },
  noneFound: {
    Guide:
      'Solus can download its own Python just for these tools, or you can choose one you have.',
    Expert: 'Install the managed Python or choose an interpreter.'
  },
  managed: {
    Guide:
      "This is Python 3.12 from python-build-standalone, about 30 MB, stored in Solus's app-data folder. Nothing else on your computer changes.",
    Expert: 'CPython 3.12 (python-build-standalone), ~30 MB, app-data folder.'
  },
  choiceChanged: {
    Guide: 'The tools were built with a different Python, so they need to be set up again.',
    Expert: 'Choice saved. Tools need setup.'
  },
  installing: {
    Guide: "Installing each tool's packages. This can take a few minutes.",
    Expert: 'Provisioning…'
  },
  needsSetup: {
    Guide:
      "Some tools aren't set up on this computer yet. Install builds them from the Python above.",
    Expert: 'Tools need setup.'
  },
  partial: {
    Guide: "Some tools couldn't be set up. The others are ready to use.",
    Expert: 'Setup incomplete.'
  },
  ready: {
    Guide: 'Every tool is set up and ready.',
    Expert: 'Ready.'
  },
  isVenv: {
    Guide:
      "That Python is a virtual environment: a private copy made from another Python. Solus can't build tools from it, so choose the Python it was made from instead.",
    Expert: 'Virtual environment refused. Choose its base interpreter.'
  },
  unavailable: {
    Guide:
      "Solus couldn't reach its local tools helper, so it can't check Python right now. Restart Solus and try again.",
    Expert: 'Local tools helper unavailable.'
  }
} as const satisfies Record<string, ByMode>

export const LEARN_MORE =
  'Each tool gets a virtual environment: a folder holding only its own packages, so tools never conflict with each other or with your projects. Solus installs only the exact package versions and checksums that ship with the app.'

/** Tool display names; unknown forks show their id. */
const FORK_NAMES: Readonly<Record<string, string>> = {
  kicad: 'KiCad',
  code: 'Code',
  local: 'Local',
  altium: 'Altium',
  gazebo: 'Gazebo',
  isaac: 'Isaac'
}

/** The OS a platform-limited tool runs on (wireflow "— (Windows only)"). */
const FORK_PLATFORM: Readonly<Record<string, string>> = {
  altium: 'Windows',
  gazebo: 'Linux and macOS',
  isaac: 'Linux'
}

export const forkName = (fork: string): string => FORK_NAMES[fork] ?? fork

export const unsupportedPlatform = (fork: string): string =>
  FORK_PLATFORM[fork] ? `— (${FORK_PLATFORM[fork]} only)` : '— (not for this OS)'

/** Why a detected interpreter cannot be used. */
export function candidateReason(code: RuntimeErrorCode | null, version: string | null): string {
  const minor = version?.split('.').slice(0, 2).join('.')
  switch (code) {
    case 'python_unsupported_version':
      return `${minor ?? 'This version'} — Solus needs 3.12 or 3.13`
    case 'python_not_cpython':
      return 'Not CPython — Solus needs CPython'
    case 'python_store_alias':
      return 'Microsoft Store Python is not supported'
    case 'python_is_venv':
      return 'Virtual environment — choose the Python it was made from'
    default:
      return "Couldn't run it"
  }
}

/** The inline message for a refused choice. */
export function chooseErrorMessage(code: RuntimeErrorCode, mode: SolMode): string {
  switch (code) {
    case 'python_is_venv':
      return COPY.isVenv[mode]
    case 'python_unsupported_version':
      return 'That Python is not 3.12 or 3.13, so the choice was not saved.'
    case 'python_not_cpython':
      return 'That interpreter is not CPython, so the choice was not saved.'
    case 'python_store_alias':
      return 'Microsoft Store Python is not supported. Choose another interpreter.'
    case 'python_probe_failed':
      return "That file didn't run as Python, so the choice was not saved."
    default:
      return "The choice couldn't be saved."
  }
}

/** The fix hint shown under a failed tool or run error. */
export function fixHint(code: RuntimeErrorCode | null): string {
  switch (code) {
    case 'network_unreachable':
      return 'Check your internet connection, then Repair.'
    case 'venv_copies_unhealthy':
      return 'This Python cannot be copied. Use the Solus-managed Python, then Repair.'
    case 'wheel_unavailable':
      return 'A package has no build for this Python. Choose Python 3.12, then Repair.'
    case 'disk_full':
      return 'Free some disk space, then Repair.'
    case 'python_is_venv':
      return 'Choose the Python this virtual environment was made from, then Repair.'
    case 'managed_not_installed':
      return 'Install the Solus-managed Python first.'
    case 'managed_hash_mismatch':
    case 'managed_download_failed':
      return "The managed Python couldn't be downloaded. Choose an interpreter instead."
    case 'cancelled':
      return 'Setup was cancelled. Repair to finish it.'
    default:
      return 'Repair to try again.'
  }
}

/** Settings › Needs attention › Local tools need setup — the card's body. */
export const attentionBody = (tools: readonly string[], mode: SolMode): string =>
  mode === 'Guide'
    ? `${tools.join(', ')} can't run until Solus sets up their Python environments on this computer.`
    : `${tools.join(', ')}: setup needed.`

export const stepLabel = (step: string, done: number, total: number | null): string =>
  total === null ? `${step}…` : `${step} ${done}/${total}`
