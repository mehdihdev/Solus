// SOLUSDEV-317: one org row's details — pending, the verified hint per mode,
// the assigner fallback, and the live region.
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { githubText } from './githubOrgCopy'
import { ASSIGNED, FREE, VERIFIED } from './githubOrgRoster.fixtures'
import { GitHubOrgMemberRow, type GitHubOrgMemberRowProps } from './GitHubOrgMemberRow'

const props = (over: Partial<GitHubOrgMemberRowProps> = {}): GitHubOrgMemberRowProps => ({
  member: FREE,
  index: 0,
  state: undefined,
  options: [],
  mode: 'Guide',
  onAssign: vi.fn(),
  onUnassign: vi.fn(),
  onInvite: vi.fn(),
  onFind: vi.fn(),
  ...over
})

const renderRow = (over: Partial<GitHubOrgMemberRowProps> = {}): void => {
  render(
    <ul>
      <GitHubOrgMemberRow {...props(over)} />
    </ul>
  )
}

describe('GitHubOrgMemberRow', () => {
  it('while pending: a spinner, Invite disabled, the picker trigger kept focusable', () => {
    renderRow({ state: { pending: true, error: null, announce: null } })
    expect(screen.getByRole('button', { name: 'Assign' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Invite @octo' })).toBeDisabled()
  })

  it('Expert keeps the verified hint to the chip tooltip', () => {
    renderRow({ member: VERIFIED, mode: 'Expert' })
    expect(screen.getByTitle(githubText('verified_hint', 'Expert'))).toBeInTheDocument()
    expect(screen.queryByText(githubText('verified_hint', 'Expert'))).toBeNull()
  })

  it('names a removed assigner as a former member', () => {
    const member = {
      ...ASSIGNED,
      assignment: { ...ASSIGNED.assignment!, assigned_by: { user_id: 'gone', name: null } }
    }
    renderRow({ member })
    expect(screen.getByText(/assigned by a former member/)).toBeInTheDocument()
  })

  it('keeps an empty live region mounted, and fills it on an announcement', () => {
    const { rerender } = render(
      <ul>
        <GitHubOrgMemberRow {...props()} />
      </ul>
    )
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    rerender(
      <ul>
        <GitHubOrgMemberRow
          {...props({
            state: {
              pending: false,
              error: null,
              announce: { key: 'unassign_done', vars: { login: 'octo' } }
            }
          })}
        />
      </ul>
    )
    expect(screen.getByRole('status')).toHaveTextContent('@octo is no longer shown')
  })
})
