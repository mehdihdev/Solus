// Billing › Credits (SOLUSDEV-325): balance + cycle meter, packs with the
// balance-after line, the no-packs CTA, the "from SOL" focus strip, and the
// post-checkout confirmation.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreditsSection, type CreditsSectionProps } from './CreditsSection'

const USAGE = {
  used: 941,
  allowance: 10000,
  balance: 9059,
  cycle_start: '2026-11-10T00:00:00Z',
  cycle_end: '2026-12-10T00:00:00Z'
}

function setup(over: Partial<CreditsSectionProps> = {}): CreditsSectionProps {
  const props: CreditsSectionProps = {
    credits: 9059,
    unlimited: false,
    usage: USAGE,
    packs: [
      { price_id: 'price_10', credits: 1000, usd: 10 },
      { price_id: 'price_25', credits: 2600, usd: 25 }
    ],
    packsAvailable: true,
    disabled: false,
    onBuy: vi.fn(),
    fromSol: false,
    onBackToSol: vi.fn(),
    onComparePlans: vi.fn(),
    purchase: null,
    onRefresh: vi.fn(),
    ...over
  }
  render(<CreditsSection {...props} />)
  return props
}

describe('CreditsSection', () => {
  it('shows the balance and the cycle meter from the usage endpoint', () => {
    setup()
    expect(screen.getByRole('region', { name: 'Credits' })).toBeInTheDocument()
    expect(screen.getByText('9,059')).toBeInTheDocument()
    expect(screen.getByText('941 of 10,000 used this cycle')).toBeInTheDocument()
    expect(screen.getByText('Resets December 10, 2026')).toBeInTheDocument()
  })

  it('omits the meter when usage is unavailable', () => {
    setup({ usage: null })
    expect(screen.getByText('9,059')).toBeInTheDocument()
    expect(screen.queryByText(/used this cycle/)).not.toBeInTheDocument()
  })

  it('shows what each pack adds and the balance after buying it', async () => {
    const props = setup()
    expect(screen.getByText('+1,000 credits')).toBeInTheDocument()
    expect(screen.getByText('→ 10,059 after purchase')).toBeInTheDocument()
    expect(screen.getByText('→ 11,659 after purchase')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Buy' })[1])
    expect(props.onBuy).toHaveBeenCalledWith('price_25')
  })

  it('disables Buy while busy or degraded', () => {
    setup({ disabled: true })
    for (const b of screen.getAllByRole('button', { name: 'Buy' })) expect(b).toBeDisabled()
  })

  it('never dead-ends without packs: explains the refill and offers Compare plans', async () => {
    const props = setup({ packsAvailable: false })
    expect(screen.getByText("Credit packs aren't available right now.")).toBeInTheDocument()
    expect(screen.getByText(/next 10,000 credits arrive December 10, 2026/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Buy' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /compare plans/i }))
    expect(props.onComparePlans).toHaveBeenCalled()
  })

  it('treats an empty pack list as unavailable', () => {
    setup({ packs: [] })
    expect(screen.getByText("Credit packs aren't available right now.")).toBeInTheDocument()
  })

  it('shows the "Adding credits for SOL" strip only when arriving from SOL', async () => {
    const props = setup({ fromSol: true })
    expect(screen.getByText('Adding credits for SOL')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /back to sol/i }))
    expect(props.onBackToSol).toHaveBeenCalled()
  })

  it('has no strip and no Back to SOL when opened from the rail', () => {
    setup()
    expect(screen.queryByText('Adding credits for SOL')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /back to sol/i })).not.toBeInTheDocument()
  })
})

describe('CreditsSection purchase confirmation', () => {
  it('confirms a purchase once the new balance has landed', () => {
    setup({ credits: 11659, purchase: { credits: 2600, balanceBefore: 9059 }, fromSol: true })
    expect(screen.getByRole('status')).toHaveTextContent('+2,600 credits added')
    expect(screen.queryByText('Adding credits for SOL')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /back to sol/i })).toBeInTheDocument()
  })

  it('says credits are on the way while the webhook is still landing', () => {
    setup({ credits: 9059, purchase: { credits: 2600, balanceBefore: 9059 } })
    expect(screen.getByRole('status')).toHaveTextContent('Payment received — adding your credits…')
    expect(screen.queryByRole('button', { name: /back to sol/i })).not.toBeInTheDocument()
  })

  it('offers Refresh while the credits are landing', async () => {
    const props = setup({ purchase: { credits: 2600, balanceBefore: 9059 } })
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(props.onRefresh).toHaveBeenCalled()
  })

  it('treats any loaded balance as landed when the balance before was unknown', () => {
    setup({ credits: 2600, purchase: { credits: 2600, balanceBefore: null } })
    expect(screen.getByRole('status')).toHaveTextContent('+2,600 credits added')
  })

  it('confirms without SOL wording or Back to SOL when opened from the rail', () => {
    setup({ credits: 11659, purchase: { credits: 2600, balanceBefore: 9059 } })
    expect(screen.getByRole('status')).toHaveTextContent('Payment received.')
    expect(screen.queryByText(/SOL can keep going/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /back to sol/i })).not.toBeInTheDocument()
  })

  it('shows the strip without a dead Back button when there is no navigation', () => {
    setup({ fromSol: true, onBackToSol: null })
    expect(screen.getByText('Adding credits for SOL')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /back to sol/i })).not.toBeInTheDocument()
  })

  it('shows Unlimited for development accounts', () => {
    setup({ unlimited: true, credits: null })
    expect(screen.getByText('Unlimited (development)')).toBeInTheDocument()
  })
})
