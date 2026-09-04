// SOLUSDEV-235 / EXT-12 — React wiring of a BridgeHost to an iframe ref.
// The iframe element itself (sandbox, src, the loading/ready/error state
// machine) is EXT-13's; this hook only owns the message plumbing:
//
//   window 'message' → host (filtered to THIS frame's window)
//   iframe 'load'    → host.init()        (§6.2: load → init → ui.ready)
//   focus / theme / project store changes → host events (§6.7)
//   unmount          → host.dispose()
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { buildThemeVars } from '../../../theme/applyTheme'
import { selectFocusedEntity, useFocusStore } from '../../workspace/focusStore'
import { toSharedFocus } from '../../workspace/useSharedFocus'
import type { BridgeDeps, SettingsValues } from './bridgeDeps'
import { createBridgeHost, type BridgeFrame, type BridgeHost } from './bridgeHost'
import { defaultBridgeDeps } from './defaultDeps'
import type { BridgePolicy } from './policySnapshot'

export interface UseExtensionBridgeOptions {
  readonly frameRef: RefObject<HTMLIFrameElement | null>
  readonly policy: BridgePolicy
  readonly settings?: SettingsValues
  /** Injectable for tests; defaults to the production wiring. */
  readonly deps?: BridgeDeps
  readonly onReady?: () => void
}

export interface ExtensionBridgeHandle {
  /** `ui.ready` received. */
  readonly ready: boolean
  /** Malformed messages from this frame (DEV badge tooltip). */
  readonly dropped: number
}

const EMPTY_SETTINGS: SettingsValues = {}

/** The frame adapter reads the ref lazily: the iframe may (re)mount after the host. */
function frameAdapter(frameRef: RefObject<HTMLIFrameElement | null>): BridgeFrame {
  return {
    postMessage: (message) => frameRef.current?.contentWindow?.postMessage(message, '*'),
    isSource: (source) => {
      const target = frameRef.current?.contentWindow ?? null
      return target !== null && source === target
    }
  }
}

/** Forward store changes as §6.7 events, deduplicated so a store emission that
 *  did not change the projected value stays silent. */
function subscribeStores(host: BridgeHost, projectId: string): () => void {
  let focusKey = ''
  let themeKey = ''
  let sentProject = projectId
  const unsubs = [
    useFocusStore.subscribe((state) => {
      const focus = toSharedFocus(selectFocusedEntity(state), projectId)
      const key = focus ? `${focus.entity.entityId}` : ''
      if (key === focusKey) return
      focusKey = key
      host.sendEvent('focus.changed', focus)
    }),
    useSettingsStore.subscribe((s) => {
      const key = `${s.theme}/${s.accent}`
      if (key === themeKey) return
      themeKey = key
      host.sendEvent('theme.changed', buildThemeVars(s.theme, s.accent))
    }),
    useWorkspaceStore.subscribe((s) => {
      const next = s.project?.id
      if (next === undefined || next === sentProject) return
      sentProject = next
      // The project UUID never crosses to the frame (L2); the frame is remounted anyway.
      host.sendEvent('project.changed', {})
    })
  ]
  return () => unsubs.forEach((u) => u())
}

export function useExtensionBridge(options: UseExtensionBridgeOptions): ExtensionBridgeHandle {
  const { frameRef, policy, onReady } = options
  const settings = options.settings ?? EMPTY_SETTINGS
  const deps = useMemo(() => options.deps ?? defaultBridgeDeps(), [options.deps])
  const [ready, setReady] = useState(false)
  const [dropped, setDropped] = useState(0)
  const hostRef = useRef<BridgeHost | null>(null)
  // Latest-value refs so the host is not rebuilt when only these change.
  const policyRef = useRef(policy)
  const settingsRef = useRef(settings)
  const onReadyRef = useRef(onReady)
  useEffect(() => {
    policyRef.current = policy
    settingsRef.current = settings
    onReadyRef.current = onReady
  })

  const { extensionId, version, projectId, mode } = policy

  useEffect(() => {
    const host = createBridgeHost({
      frame: frameAdapter(frameRef),
      policy: policyRef.current,
      settings: settingsRef.current,
      deps,
      onReady: () => {
        setReady(true)
        onReadyRef.current?.()
      }
    })
    hostRef.current = host
    const onMessage = (event: MessageEvent): void => {
      void host.handleMessage(event).then(() => setDropped(host.stats().dropped))
    }
    const onLoad = (): void => host.init()
    const frame = frameRef.current
    window.addEventListener('message', onMessage)
    frame?.addEventListener('load', onLoad)
    const unsubscribe = subscribeStores(host, projectId)
    return () => {
      unsubscribe()
      frame?.removeEventListener('load', onLoad)
      window.removeEventListener('message', onMessage)
      host.dispose()
      hostRef.current = null
      setReady(false)
    }
    // The host is keyed by the frame's identity (§6.7: a project switch remounts).
  }, [frameRef, deps, extensionId, version, projectId, mode])

  useEffect(() => {
    hostRef.current?.updatePolicy(policy)
  }, [policy])

  const appliedSettings = useRef(settings)
  useEffect(() => {
    if (appliedSettings.current === settings) return
    appliedSettings.current = settings
    hostRef.current?.updateSettings(settings)
  }, [settings])

  return { ready, dropped }
}
