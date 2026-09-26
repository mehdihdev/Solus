import { useEffect, useRef, useState } from 'react'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { createOverlayHandoff, orbPortFromBridge, type OverlayHandoff } from '../sol/overlayHandoff'
import { useSolWindowStore } from '../sol/solWindowStore'
import { workspaceSessionGeneration } from '../graph/workspaceSession'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { GuideDetail } from './guideApi'

export function useNativeGuideHandoff(
  guide: GuideDetail | null,
  expert: boolean
): { message: string; start: () => Promise<void> } {
  const [message, setMessage] = useState('')
  const handoff = useRef<OverlayHandoff | null>(null)
  const request = useRef(0)
  useEffect(() => {
    const cancel = (): void => {
      request.current += 1
      const session = handoff.current
      handoff.current = null
      try {
        if (session?.activeHandoffId()) session.dismiss('focus_changed')
      } finally {
        session?.dispose()
      }
    }
    const offMode = useSolWindowStore.subscribe((next, previous) => {
      if (next.state?.actionMode !== previous.state?.actionMode) cancel()
    })
    const offProject = useWorkspaceStore.subscribe((next, previous) => {
      if (next.project?.id !== previous.project?.id) cancel()
    })
    const offAccount = useAuthStore.subscribe((next, previous) => {
      if (next.status !== previous.status || next.user?.email !== previous.user?.email) cancel()
    })
    return () => {
      offMode()
      offProject()
      offAccount()
      cancel()
    }
  }, [guide])
  const isCurrent = (current: number, generation: number): boolean =>
    request.current === current &&
    workspaceSessionGeneration() === generation &&
    useSolWindowStore.getState().state?.actionMode === 'guide'
  const start = async (): Promise<void> => {
    if (!guide || handoff.current?.activeHandoffId()) return
    const current = ++request.current
    const generation = workspaceSessionGeneration()
    const bridge = nativeOverlayBridge()
    const target = await nativeGuideTarget()
    if (!isCurrent(current, generation)) return
    if (!bridge || !target || target.tool !== guide.tool) {
      setMessage(
        'Native overlay is unavailable. Continue with the side-panel steps; screen capture uses your existing consent setting.'
      )
      return
    }
    attachGuideOverlay(guide, expert, bridge, target, handoff, setMessage)
  }
  return { message, start }
}

function nativeOverlayBridge(): Parameters<typeof orbPortFromBridge>[0] | undefined {
  return (window as unknown as { solus?: { orbOverlay?: Parameters<typeof orbPortFromBridge>[0] } })
    .solus?.orbOverlay
}
async function nativeGuideTarget() {
  return getDesktopSolBridge()
    ?.getGuideTarget?.()
    .catch(() => null)
}

function attachGuideOverlay(
  guide: GuideDetail,
  expert: boolean,
  bridge: Parameters<typeof orbPortFromBridge>[0],
  target: NonNullable<Awaited<ReturnType<typeof nativeGuideTarget>>>,
  handoff: React.RefObject<OverlayHandoff | null>,
  setMessage: (message: string) => void
): void {
  const steps = guide.steps
  let index = 0
  const toStep = (position: number): Parameters<OverlayHandoff['advance']>[0] => {
    const step = steps[position]
    return {
      stepId: `${guide.id}:${step.step_number}`,
      index: position,
      total: steps.length,
      title: step.label ?? guide.title,
      instruction: expert ? step.note_expert : step.note_guide,
      control: {
        tool: target.tool,
        controlId: step.control_id,
        locator: step.available && !step.tentative && !step.stale ? step.locator : null
      }
    }
  }
  if (!steps.length) return
  const session = createOverlayHandoff(orbPortFromBridge(bridge), {
    onStepCompleted: (id) => {
      if (index >= steps.length || id !== toStep(index).stepId) return
      index += 1
      if (index < steps.length) session.advance(toStep(index))
      else session.dismiss('completed')
    },
    onFailed: () => setMessage('Overlay could not attach. Continue with the side-panel steps.'),
    onReclaim: () => setMessage('Continue with the side-panel steps.'),
    onEnded: () => setMessage('Overlay closed. The guide remains here.')
  })
  handoff.current?.dispose()
  handoff.current = session
  setMessage(
    'Overlay requested. If the control location is unknown, continue with the side-panel steps.'
  )
  try {
    session.start({ focus: null, step: toStep(0), target })
  } catch {
    session.dispose()
    setMessage('Overlay could not attach. Continue with the side-panel steps.')
  }
}
