// SOLUSDEV-317: the members list asks the org members section to work from a teammate.
import { beforeEach, describe, expect, it } from 'vitest'
import { useGithubAssignFocusStore } from './githubAssignFocusStore'

beforeEach(() => useGithubAssignFocusStore.setState({ request: null }))

describe('githubAssignFocusStore', () => {
  it('records a request with a fresh sequence each time', () => {
    const { requestAssign } = useGithubAssignFocusStore.getState()
    requestAssign('t1', 'u1')
    const first = useGithubAssignFocusStore.getState().request
    requestAssign('t1', 'u1')
    const second = useGithubAssignFocusStore.getState().request
    expect(first).toMatchObject({ teamId: 't1', userId: 'u1' })
    expect(second!.seq).toBeGreaterThan(first!.seq)
    expect(second).not.toBe(first)
  })

  it('clears', () => {
    useGithubAssignFocusStore.getState().requestAssign('t1', 'u1')
    useGithubAssignFocusStore.getState().clear()
    expect(useGithubAssignFocusStore.getState().request).toBeNull()
  })
})
