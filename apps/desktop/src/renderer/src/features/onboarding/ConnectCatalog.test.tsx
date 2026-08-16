// The shared catalog surface (SOLUSDEV-165): tiles from the live registry,
// each opening the connect wizard. Used by onboarding and the Sources page so
// the connect experience is one implementation.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ConnectCatalog } from './ConnectCatalog'
import { useOnboardingStore } from './onboardingStore'
import * as catalogHook from './useIntegrationCatalog'
import type { CatalogEntry } from './integrationCatalog'

const GITHUB: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'GH',
  mode: 'oauth',
  configFields: ['repo', 'branch'],
  selection: { mode: 'single', config_key: 'repo', label: 'repository' },
  accessModes: null
}

beforeEach(() => {
  useOnboardingStore.getState().reset()
  vi.spyOn(catalogHook, 'useIntegrationCatalog').mockReturnValue([GITHUB])
})

describe('ConnectCatalog', () => {
  it('lists a tile per live catalog entry', () => {
    render(<ConnectCatalog projectId="p1" />)
    expect(screen.getByText('GitHub')).toBeTruthy()
    expect(screen.getByText('Not connected')).toBeTruthy()
  })

  it('opens the connect wizard when a tile is clicked, and closes it again', () => {
    render(<ConnectCatalog projectId="p1" />)
    fireEvent.click(screen.getByText('GitHub'))
    expect(screen.getByRole('dialog', { name: 'Connect GitHub' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('says so honestly when no connectors are available', () => {
    vi.spyOn(catalogHook, 'useIntegrationCatalog').mockReturnValue([])
    render(<ConnectCatalog projectId="p1" />)
    expect(screen.getByText('No connectors are available to add right now.')).toBeTruthy()
  })
})
