// SOLUSDEV-244 / HOME H5: the limit is shown with its upgrade path.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PlanLimitNotice } from './PlanLimitNotice'

describe('PlanLimitNotice', () => {
  it('states the server sentence and routes Upgrade to billing', async () => {
    const onUpgrade = vi.fn()
    render(
      <PlanLimitNotice message="You're at your collaborative-team limit." onUpgrade={onUpgrade} />
    )
    expect(screen.getByRole('note')).toHaveTextContent("You're at your collaborative-team limit.")
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(onUpgrade).toHaveBeenCalledTimes(1)
  })

  it('stands alone without an upgrade path', () => {
    render(<PlanLimitNotice message="Limit." />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})
