import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { IntegrationsSection } from './IntegrationsSection'
import { useOnboardingStore } from '../../onboarding/onboardingStore'
import { INTEGRATIONS } from '../../onboarding/integrations.constants'

beforeEach(() => {
  useOnboardingStore.getState().reset()
})

describe('IntegrationsSection', () => {
  it('lists every connector in the catalog', () => {
    render(<IntegrationsSection />)
    for (const integration of INTEGRATIONS) {
      expect(screen.getByText(integration.name)).toBeInTheDocument()
    }
  })

  it('marks a connected source as CONNECTED and others as not', () => {
    useOnboardingStore.getState().setConnection('github', { phase: 'done' })
    render(<IntegrationsSection />)
    expect(screen.getByText('● CONNECTED')).toBeInTheDocument()
    // The remaining connectors are not connected.
    expect(screen.getAllByText('○ NOT CONNECTED')).toHaveLength(INTEGRATIONS.length - 1)
  })
})
