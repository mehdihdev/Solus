import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PrivacySection } from './PrivacySection'
import { settingsData } from '../settings.fixtures'
import { PRIVACY_POLICY_URL } from '../legalLinks.constants'

vi.mock('./AccountSection', () => ({ DeleteAccountRow: () => <div>delete-account-row</div> }))

describe('PrivacySection', () => {
  it('reflects the current consent state', () => {
    render(<PrivacySection data={settingsData({ consent: true })} />)
    expect(screen.getByRole('switch', { name: 'Usage data' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
  })

  it('opts out through the action', async () => {
    const data = settingsData({ consent: true })
    render(<PrivacySection data={data} />)
    await userEvent.click(screen.getByRole('switch', { name: 'Usage data' }))
    expect(data.actions.setConsent).toHaveBeenCalledWith(false)
  })

  it('opts back in through the action', async () => {
    const data = settingsData({ consent: false })
    render(<PrivacySection data={data} />)
    await userEvent.click(screen.getByRole('switch', { name: 'Usage data' }))
    expect(data.actions.setConsent).toHaveBeenCalledWith(true)
  })

  it('surfaces the consent error inline', () => {
    render(
      <PrivacySection
        data={settingsData({ errors: { sol_mode: null, consent: 'save failed', name: null } })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('save failed')
  })

  it('links the Privacy Policy and holds the delete-account danger row', () => {
    render(<PrivacySection data={settingsData()} />)
    expect(screen.getByRole('link', { name: /Privacy Policy/ })).toHaveAttribute(
      'href',
      PRIVACY_POLICY_URL
    )
    expect(screen.getByText('delete-account-row')).toBeInTheDocument()
  })
})
