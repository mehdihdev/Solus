import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAuthStore } from '../../../store/authStore'

/** Every scope transition expires work, including batched account A→B→A changes. */
export function useHardwareGeneration(projectId: string): {
  generation: React.RefObject<number>
  authEpoch: number
} {
  const generation = useRef(0)
  const [authEpoch, setAuthEpoch] = useState(0)
  useLayoutEffect(() => {
    generation.current += 1
    return () => {
      generation.current += 1
    }
  }, [projectId])
  useEffect(
    () =>
      useAuthStore.subscribe((next, previous) => {
        if (
          next.accessToken !== previous.accessToken ||
          next.user !== previous.user ||
          next.status !== previous.status
        ) {
          generation.current += 1
          setAuthEpoch((epoch) => epoch + 1)
        }
      }),
    []
  )
  return { generation, authEpoch }
}
