import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hostedApi from '../../lib/api/resources.hosted'
import { AccountHostedRow } from './AccountHostedRow'
import { useAuthStore } from '../../store/authStore'
vi.mock('../../lib/api/resources.hosted', () => ({
  getAccountHosted: vi.fn(),
  startAccountHosted: vi.fn(),
  exchangeAccountHosted: vi.fn(),
  probeAccountHosted: vi.fn()
}))
const hosted = {
  server: 'fs',
  display_name: 'FeatureScript',
  notice: 'Runs as your account',
  subscribe_url: null
}
beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ accessToken: 'test-session' })
})
it('loads durable account readiness without requiring a project', async () => {
  vi.mocked(hostedApi.getAccountHosted).mockResolvedValue({
    server: 'fs',
    state: 'ready',
    tool_count: 3
  })
  render(<AccountHostedRow connectionId="c1" hosted={hosted} />)
  expect(await screen.findByText('FeatureScript ready')).toBeInTheDocument()
  expect(hostedApi.getAccountHosted).toHaveBeenCalledWith('c1', 'fs')
})
it('discloses incomplete setup and allows a fresh capability check', async () => {
  vi.mocked(hostedApi.getAccountHosted).mockResolvedValue({
    server: 'fs',
    state: 'subscription_required',
    tool_count: 0
  })
  vi.mocked(hostedApi.probeAccountHosted).mockResolvedValue({
    server: 'fs',
    state: 'ready',
    tool_count: 3
  })
  render(<AccountHostedRow connectionId="c1" hosted={hosted} />)
  expect(await screen.findByText(/Runs as your account/)).toBeInTheDocument()
  await userEvent.click(await screen.findByRole('button', { name: 'Check FeatureScript' }))
  expect(await screen.findByText('FeatureScript ready')).toBeInTheDocument()
})
