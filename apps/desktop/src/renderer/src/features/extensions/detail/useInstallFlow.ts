// SOLUSDEV-235 — the detail page's install / update / uninstall state machine:
// which permissions step is open, whether a write is in flight, and what the
// last outcome said. Pure UI state over `ExtensionActions`; the server writes
// and the bundle cache live in the actions.
import { useCallback, useState } from 'react'
import type { PermissionScope } from '@solus/shared-types'
import type { ExtensionGrants, ExtensionInstallState, ExtensionView } from '../extension.types'
import type { ExtensionActionResult, ExtensionActions } from '../extensionActions'
import { declaredGrants } from '../extensionLogic'
import type { GrantMode } from './GrantPermissionsModal'

export interface GrantStep extends ExtensionGrants {
  readonly mode: GrantMode
}

export interface Notice {
  readonly kind: 'note' | 'error'
  readonly text: string
}

export interface InstallFlow {
  readonly step: GrantStep | null
  readonly busy: boolean
  readonly stepError: string | null
  readonly notice: Notice | null
  /** Open the permissions step for a first install (needs the manifest). */
  beginInstall: () => void
  /** Try the update with the current grants; a `grants_required` answer opens the step. */
  beginUpdate: () => Promise<void>
  /** Grant exactly what the open step lists, then install or update. */
  grant: () => Promise<void>
  cancel: () => void
  /** Returns true when the server removed the install. */
  uninstall: () => Promise<boolean>
}

function uniq<T>(values: readonly T[]): T[] {
  return [...new Set(values)]
}

/** The current grants plus the step's additions — what a widening update sends. */
export function widenedGrants(
  state: ExtensionInstallState,
  step: ExtensionGrants
): ExtensionGrants {
  return {
    scopes: uniq<PermissionScope>([...state.grantedScopes, ...step.scopes]),
    network: uniq([...state.grantedNetwork, ...step.network])
  }
}

function noticeOf(result: ExtensionActionResult): Notice | null {
  if (!result.ok) return { kind: 'error', text: result.message }
  if (!result.note) return null
  return { kind: result.bundle === 'failed' ? 'error' : 'note', text: result.note }
}

export function useInstallFlow(view: ExtensionView, actions: ExtensionActions): InstallFlow {
  const [step, setStep] = useState<GrantStep | null>(null)
  const [busy, setBusy] = useState(false)
  const [stepError, setStepError] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const { slug } = view.catalog

  const run = useCallback(
    async (write: () => Promise<ExtensionActionResult>, inStep: boolean): Promise<void> => {
      setBusy(true)
      const result = await write()
      setBusy(false)
      if (!result.ok && result.code === 'grants_required' && result.grantsRequired) {
        setStep({ mode: 'update', ...result.grantsRequired })
        setStepError(null)
        return
      }
      if (result.ok || !inStep) {
        setStep(null)
        setStepError(null)
        setNotice(noticeOf(result))
        return
      }
      setStepError(result.message)
    },
    []
  )

  const beginInstall = useCallback((): void => {
    if (!view.manifest) return
    setStepError(null)
    setStep({ mode: 'install', ...declaredGrants(view.manifest) })
  }, [view.manifest])

  const beginUpdate = useCallback(
    (): Promise<void> => run(() => actions.update(slug), false),
    [actions, run, slug]
  )

  const grant = useCallback((): Promise<void> => {
    if (!step) return Promise.resolve()
    return step.mode === 'install'
      ? run(() => actions.install(slug, { scopes: step.scopes, network: step.network }), true)
      : run(() => actions.update(slug, widenedGrants(view.state, step)), true)
  }, [actions, run, slug, step, view.state])

  const cancel = useCallback((): void => {
    setStep(null)
    setStepError(null)
  }, [])

  const uninstall = useCallback(async (): Promise<boolean> => {
    const result = await actions.uninstall(slug)
    setNotice(noticeOf(result))
    return result.ok
  }, [actions, slug])

  return { step, busy, stepError, notice, beginInstall, beginUpdate, grant, cancel, uninstall }
}
