// ADR-041 amendment 2026-10-28 (SOLUSDEV-319 drive slice 3b): the drive agent
// trusts any process satisfying Solus.app's code requirement, so a packaged
// Solus.app must only ever run Solus code with Solus configuration. The fuses
// cover ELECTRON_RUN_AS_NODE, NODE_OPTIONS and the Node --inspect flags; this
// refuses the Chromium/V8 switches that would let another process drive main
// (a remote debugger) or change V8's behaviour. Pure; index.ts calls it first.

export const FORBIDDEN_PACKAGED_SWITCHES: readonly string[] = [
  'remote-debugging-port',
  'remote-debugging-pipe',
  'inspect',
  'inspect-brk',
  'inspect-port',
  'js-flags'
]

export interface PackagedGuardInput {
  isPackaged: boolean
  argv: readonly string[]
  /** `app.commandLine.hasSwitch`. */
  hasSwitch(name: string): boolean
}

/** `--name`, `-name`, `--name=…` or `-name=…` (Chromium accepts one dash). */
function argvHasSwitch(argv: readonly string[], name: string): boolean {
  return argv.some((arg) => {
    const bare = arg.replace(/^--?/, '')
    if (bare === arg) return false // not a switch at all
    return bare === name || bare.startsWith(`${name}=`)
  })
}

/** The first forbidden switch present in a packaged launch, or null. */
export function forbiddenPackagedSwitch(input: PackagedGuardInput): string | null {
  if (!input.isPackaged) return null
  return (
    FORBIDDEN_PACKAGED_SWITCHES.find(
      (name) => input.hasSwitch(name) || argvHasSwitch(input.argv, name)
    ) ?? null
  )
}
