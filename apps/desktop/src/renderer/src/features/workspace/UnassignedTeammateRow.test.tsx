// SOLUSDEV-317: a teammate row shows the outcome of the account it picked.
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ADA } from './githubOrgRoster.fixtures'
import { UnassignedTeammateRow } from './UnassignedTeammateRow'

describe('UnassignedTeammateRow', () => {
  it('assigns the picked account and shows that account’s refusal', async () => {
    const onAssign = vi.fn()
    const options = [{ id: '7', label: '@octo', detail: 'Not on Solus', disabled: false }]
    const { rerender } = render(
      <ul>
        <UnassignedTeammateRow
          teammate={ADA}
          index={0}
          options={options}
          rows={{}}
          mode="Expert"
          openRequest={0}
          onAssign={onAssign}
        />
      </ul>
    )
    await userEvent.click(screen.getByRole('button', { name: 'Pick GitHub account' }))
    await userEvent.click(screen.getByRole('option', { name: /@octo/ }))
    expect(onAssign).toHaveBeenCalledWith(7)
    rerender(
      <ul>
        <UnassignedTeammateRow
          teammate={ADA}
          index={0}
          options={options}
          rows={{
            7: { pending: false, error: { key: 'assign_failed', vars: {} }, announce: null }
          }}
          mode="Expert"
          openRequest={0}
          onAssign={onAssign}
        />
      </ul>
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Assignment failed. Retry.')
  })
})
