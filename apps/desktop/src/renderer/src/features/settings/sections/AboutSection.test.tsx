import { describe, it, expect, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AboutSection } from './AboutSection'
import { LEGAL_LINKS } from '../legalLinks.constants'

const w = window as unknown as { solus?: { app?: { version: () => Promise<string | null> } } }

afterEach(() => {
  delete w.solus
})

describe('AboutSection', () => {
  it('links Terms, Privacy and Contact to solusforge.com in a new browser window', () => {
    render(<AboutSection />)
    for (const link of LEGAL_LINKS) {
      const a = screen.getByRole('link', { name: new RegExp(link.label) })
      expect(a).toHaveAttribute('href', link.href)
      expect(a).toHaveAttribute('target', '_blank')
      expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })

  it('shows the desktop app version from main', async () => {
    w.solus = { app: { version: async () => '1.4.0' } }
    render(<AboutSection />)
    expect(await screen.findByText('Solus 1.4.0')).toBeInTheDocument()
  })

  it('omits the version outside Electron rather than inventing one', () => {
    render(<AboutSection />)
    expect(screen.queryByText(/^Solus \d/)).toBeNull()
  })
})
