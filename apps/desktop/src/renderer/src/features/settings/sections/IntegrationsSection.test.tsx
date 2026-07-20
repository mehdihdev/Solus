import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { IntegrationsSection } from './IntegrationsSection'
import { INTEGRATIONS } from '../../onboarding/integrations.constants'

describe('IntegrationsSection', () => {
  it('lists every connector in the catalog', () => {
    render(<IntegrationsSection />)
    for (const integration of INTEGRATIONS) {
      expect(screen.getByText(integration.name)).toBeInTheDocument()
    }
  })

  it('presents the catalog as available (not a fabricated connection state)', () => {
    // Honest catalog: connection is per-project, so no global CONNECTED/NOT
    // CONNECTED is shown (SOLUSDEV-152). Every connector reads "AVAILABLE".
    render(<IntegrationsSection />)
    expect(screen.getAllByText('AVAILABLE')).toHaveLength(INTEGRATIONS.length)
    expect(screen.queryByText('○ NOT CONNECTED')).not.toBeInTheDocument()
  })
})
