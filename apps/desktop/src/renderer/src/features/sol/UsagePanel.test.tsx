// SOLUSDEV-233: the SOL USAGE meter (credits, ADR-018) + low-credit top-up card.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import * as billingData from '../billing/useBillingData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { UsagePanel } from './UsagePanel'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getUsage: vi.fn() }
})
vi.mock('../billing/useBillingData', () => ({ useBillingData: vi.fn() }))
const getUsage = vi.mocked(resources.getUsage)
const useBillingData = vi.mocked(billingData.useBillingData)

const USAGE: resources.UsageApi = {
  used: 941,
  allowance: 10000,
  balance: 9059,
  cycle_start: '2026-08-10T00:00:00+00:00',
  cycle_end: '2026-09-10T00:00:00+00:00'
}

function billing(overrides: Partial<billingData.BillingData> = {}): billingData.BillingData {
  return {
    status: 'ready',
    subscription: null,
    credits: 9059,
    packs: [
      { price_id: 'pk10', credits: 1000, usd: 10 },
      { price_id: 'pk25', credits: 2600, usd: 25 }
    ],
    busy: false,
    notice: null,
    clearNotice: vi.fn(),
    startCheckout: vi.fn(),
    buyPack: vi.fn(),
    openPortal: vi.fn(),
    refresh: vi.fn(),
    ...overrides
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  useBillingData.mockReturnValue(billing())
  getUsage.mockResolvedValue(USAGE)
})

describe('UsagePanel', () => {
  it('shows the credit meter for this cycle', async () => {
    render(<UsagePanel creditsExhausted={false} />)
    await waitFor(() => expect(screen.getByText('This cycle')).toBeInTheDocument())
    expect(screen.getByText('941 / 10,000')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Credits used this cycle' })).toBeVisible()
    expect(screen.getByText(/Balance: 9,059 credits/)).toBeInTheDocument()
    // Healthy balance: no top-up nag.
    expect(screen.queryByText(/Running low on credits/)).not.toBeInTheDocument()
  })

  it('offers the credit packs when the balance runs low, and buys one', async () => {
    const data = billing()
    useBillingData.mockReturnValue(data)
    getUsage.mockResolvedValue({ ...USAGE, used: 9950, balance: 50 })
    render(<UsagePanel creditsExhausted={false} />)
    await waitFor(() => expect(screen.getByText(/Running low on credits/)).toBeInTheDocument())
    expect(screen.getByText(/Top up to keep SOL grounded/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '$10' }))
    expect(data.buyPack).toHaveBeenCalledWith('pk10')
  })

  it('escalates to "Out of credits" after a 402 turn rejection', async () => {
    getUsage.mockResolvedValue({ ...USAGE, balance: 0 })
    render(<UsagePanel creditsExhausted />)
    await waitFor(() => expect(screen.getByText('Out of credits')).toBeInTheDocument())
  })

  it('is honest offline', () => {
    useWorkspaceStore.setState({ linked: false })
    render(<UsagePanel creditsExhausted={false} />)
    expect(screen.getByText(/Usage unavailable offline/)).toBeInTheDocument()
    expect(getUsage).not.toHaveBeenCalled()
  })
})
