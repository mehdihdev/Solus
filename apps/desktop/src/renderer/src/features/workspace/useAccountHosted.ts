import { useEffect, useRef, useState } from 'react'
import type { HostedStatus, IntegrationHosted } from '../../lib/api/resources'
import * as api from '../../lib/api/resources.hosted'
import { getDesktopHostedBridge, getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { accountAddOnStep } from '../onboarding/accountAddOnStep'

interface AccountHostedState {
  status: HostedStatus | null
  busy: boolean
  error: string | null
  monitoring: boolean
  check: () => Promise<void>
  connect: () => Promise<void>
  openStore: () => Promise<void>
  stop: () => void
}

export function useAccountHosted(
  connectionId: string,
  hosted: IntegrationHosted
): AccountHostedState {
  const token = useAuthStore((state) => state.accessToken)
  const [status, setStatus] = useState<HostedStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [monitoring, setMonitoring] = useState(false)
  const generation = useRef(0)
  useEffect(() => {
    const lifetime = generation
    const current = ++lifetime.current
    setStatus(null)
    setBusy(false)
    setError(null)
    setMonitoring(false)
    if (token)
      void api.getAccountHosted(connectionId, hosted.server).then(
        (value) => {
          if (generation.current === current) setStatus(value)
        },
        () => {
          if (generation.current === current) setError('Could not read add-on status.')
        }
      )
    return () => {
      lifetime.current++
    }
  }, [connectionId, hosted.server, token])

  const run = async (operation: () => Promise<HostedStatus>): Promise<void> => {
    const current = generation.current
    setBusy(true)
    setError(null)
    try {
      const value = await operation()
      if (generation.current === current) setStatus(value)
    } catch (reason) {
      if (generation.current === current)
        setError(reason instanceof Error ? reason.message : 'Add-on setup did not finish.')
    } finally {
      if (generation.current === current) setBusy(false)
    }
  }
  const check = (): Promise<void> => run(() => api.probeAccountHosted(connectionId, hosted.server))
  const connect = (): Promise<void> =>
    run(() => connectHostedAccount(connectionId, hosted, generation, setError))
  const openStore = (): Promise<void> =>
    openHostedStore(hosted, generation, setError, setMonitoring)
  useCompletionChecks({
    monitoring,
    ready: status?.state === 'ready',
    connectionId,
    server: hosted.server,
    token,
    setStatus,
    setMonitoring
  })
  return {
    status,
    busy,
    error,
    monitoring,
    check,
    connect,
    openStore,
    stop: () => setMonitoring(false)
  }
}

interface CompletionProps {
  monitoring: boolean
  ready: boolean
  connectionId: string
  server: string
  token: string | null
  setStatus: (status: HostedStatus) => void
  setMonitoring: (value: boolean) => void
}
function useCompletionChecks({
  monitoring,
  ready,
  connectionId,
  server,
  token,
  setStatus,
  setMonitoring
}: CompletionProps): void {
  useEffect(() => {
    if (!monitoring || ready) return
    let cancelled = false
    let attempts = 0
    let pending = false
    const probe = async (): Promise<void> => {
      if (cancelled || pending || attempts >= 12) return
      pending = true
      attempts++
      try {
        const value = await api.probeAccountHosted(connectionId, server)
        if (!cancelled) setStatus(value)
      } catch {
        /* Explicit Check remains available after bounded detection. */
      } finally {
        pending = false
        if (!cancelled && attempts >= 12) setMonitoring(false)
      }
    }
    const timer = window.setInterval(() => void probe(), 5000)
    const deadline = window.setTimeout(() => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('focus', probe)
      setMonitoring(false)
    }, 60000)
    window.addEventListener('focus', probe)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.clearTimeout(deadline)
      window.removeEventListener('focus', probe)
    }
  }, [monitoring, ready, connectionId, server, token, setStatus, setMonitoring])
}

async function openHostedStore(
  hosted: IntegrationHosted,
  generation: { current: number },
  setError: (message: string) => void,
  setMonitoring: (value: boolean) => void
): Promise<void> {
  const bridge = getDesktopHostedBridge()
  if (!bridge || !hosted.subscribe_url) {
    setError('Open the vendor subscription page in the desktop app.')
    return
  }
  const current = generation.current
  try {
    const result = await bridge.openStore(hosted.subscribe_url)
    if (generation.current !== current) return
    if (!result.ok) setError('Could not open the subscription page.')
    else setMonitoring(true)
  } catch {
    if (generation.current === current) setError('Could not open the subscription page.')
  }
}

async function connectHostedAccount(
  connectionId: string,
  hosted: IntegrationHosted,
  generation: { current: number },
  setError: (message: string) => void
): Promise<HostedStatus> {
  const current = generation.current
  const bridge = getDesktopOAuthBridge()
  if (!bridge) throw new Error('Continue add-on setup in the desktop app.')
  const note = await accountAddOnStep({
    api,
    hosted,
    bridge,
    isCancelled: () => generation.current !== current,
    onProgress: () => {}
  })(connectionId)
  if (generation.current !== current) throw new Error('Setup cancelled.')
  if (note?.includes('setup incomplete')) setError(note)
  return api.getAccountHosted(connectionId, hosted.server)
}
