// SOLUSDEV-235 — detail › Overview.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OverviewTab } from './OverviewTab'
import { EXTENSION_CATALOG } from '../extensions.catalog'
import { buildView, DEFAULT_INSTALL_STATE } from '../extensionLogic'
import type { ExtensionInstallState, ExtensionView } from '../extension.types'

function viewOf(
  id: string,
  state: Partial<ExtensionInstallState> = {},
  connected: string[] = []
): ExtensionView {
  const manifest = EXTENSION_CATALOG.find((m) => m.id === id)!
  return buildView(manifest, { ...DEFAULT_INSTALL_STATE, ...state }, new Set(connected as never[]))
}

describe('OverviewTab', () => {
  it('lists what the extension adds', () => {
    render(<OverviewTab view={viewOf('experiments', { installed: true })} />)
    expect(screen.getByText('Overview widget')).toBeInTheDocument()
    expect(screen.getByText('SOL grounding')).toBeInTheDocument()
  })

  it('reports project activity honestly by install state', () => {
    const { rerender } = render(<OverviewTab view={viewOf('experiments', { installed: true })} />)
    expect(screen.getByText('IDLE')).toBeInTheDocument()
    expect(screen.getByText('No activity in this project yet.')).toBeInTheDocument()
    rerender(<OverviewTab view={viewOf('experiments', { installed: true, enabled: false })} />)
    expect(screen.getByText('DISABLED')).toBeInTheDocument()
    rerender(<OverviewTab view={viewOf('bom')} />)
    expect(screen.getByText('NOT INSTALLED')).toBeInTheDocument()
  })

  it('shows requirements with their met/unmet state', () => {
    const { rerender } = render(<OverviewTab view={viewOf('fsae-rules-checker')} />)
    const req = screen.getByTestId('detail-requires')
    expect(req).toHaveTextContent('A CAD source (Onshape) or An EDA source (KiCad, Altium)')
    expect(req.querySelector('[data-met="false"]')).not.toBeNull()
    rerender(<OverviewTab view={viewOf('fsae-rules-checker', {}, ['eda'])} />)
    expect(screen.getByTestId('detail-requires').querySelector('[data-met="true"]')).not.toBeNull()
    rerender(<OverviewTab view={viewOf('scene', { installed: true })} />)
    expect(screen.getByText('No connected source required.')).toBeInTheDocument()
  })

  it('shows credits and external links that open outside the app', () => {
    render(<OverviewTab view={viewOf('experiments', { installed: true })} />)
    expect(screen.getByText('This cycle')).toBeInTheDocument()
    expect(screen.getByText('~1')).toBeInTheDocument()
    const docs = screen.getByRole('link', { name: /Documentation/ })
    expect(docs).toHaveAttribute('target', '_blank')
    expect(docs).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('link', { name: /Source/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Report an issue/ })).toBeInTheDocument()
  })

  it('reads "none" for extensions that never spend credits', () => {
    render(<OverviewTab view={viewOf('scene', { installed: true })} />)
    expect(screen.getByText('none')).toBeInTheDocument()
  })

  it('drops a link that is not https instead of rendering it', () => {
    const manifest = EXTENSION_CATALOG.find((m) => m.id === 'scene')!
    const view = buildView(
      {
        ...manifest,
        links: { documentation: 'javascript:alert(1)', issues: 'https://ok.example' }
      },
      { ...DEFAULT_INSTALL_STATE, installed: true },
      new Set()
    )
    render(<OverviewTab view={view} />)
    expect(screen.queryByRole('link', { name: /Documentation/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Report an issue/ })).toHaveAttribute(
      'href',
      'https://ok.example'
    )
  })
})
