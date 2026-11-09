// SOLUSDEV-319 drive slice 3b, review HIGH-1: a relocated Solus.app copy with
// swapped companion files still satisfies Solus.app's code requirement at the
// main executable, so a packaged main checks its OWN bundle — nested code and
// resources included — through the native module (SecStaticCodeCheckValidity;
// false while the team ID is a placeholder). The answer is cached per launch,
// re-run at every drive-child spawn, and drive stays off (`bundle_modified`)
// until a check has passed. Dev builds skip this.

/** The slice of the native module this needs. */
interface BundleCheckModule {
  checkOwnBundle?: unknown
}

export interface BundleCheck {
  /** The latest answer; false until one completed. */
  ok(): boolean
  /** Ask again (overlapping calls share one native call). */
  check(): Promise<boolean>
}

export function createBundleCheck(
  module: () => BundleCheckModule | null,
  onChange: (ok: boolean) => void = () => undefined
): BundleCheck {
  let state = false
  let inflight: Promise<boolean> | null = null

  const ask = async (): Promise<boolean> => {
    const m = module()
    const fn = m?.checkOwnBundle
    if (typeof fn !== 'function') return false
    try {
      return (await (fn as () => Promise<unknown>).call(m)) === true
    } catch {
      return false
    }
  }

  return {
    ok: () => state,
    check() {
      inflight ??= ask().then((answer) => {
        inflight = null
        if (answer !== state) {
          state = answer
          onChange(answer)
        }
        return answer
      })
      return inflight
    }
  }
}
