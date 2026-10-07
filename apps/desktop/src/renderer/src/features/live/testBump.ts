// Test helper: deliver a live revision bump the way the account stream does, then
// wait out the coalescing window so subscribed hooks have re-rendered.
import { act } from '@testing-library/react'
import { LIVE_COALESCE_MS, useLiveRevisionStore } from '../../store/liveRevisionStore'

export async function bumpLive(...keys: string[]): Promise<void> {
  await act(async () => {
    useLiveRevisionStore.getState().bump(keys)
    await new Promise((resolve) => setTimeout(resolve, LIVE_COALESCE_MS + 40))
  })
}
