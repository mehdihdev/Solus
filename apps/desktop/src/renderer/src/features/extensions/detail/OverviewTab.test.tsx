// SOLUSDEV-235 — detail › Overview, from the manifest and the install row.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OverviewTab } from './OverviewTab'
import { manifest, viewOf } from '../testing/fixtures'

describe('OverviewTab', () => {
  it('names what a first-party bundle runs inside Solus (STORE ST3)', () => {
    const firstParty = manifest({
      schema_version: 2,
      backend: { capability: 'bom', routes: true },
      graph: { kinds: [{ name: 'item', domain: 'project' }] },
      tools: { names: ['add_item'] }
    })
    render(<OverviewTab view={viewOf({ manifest: firstParty, install: {} })} />)
    expect(screen.getByText('Runs in Solus (first-party)')).toBeInTheDocument()
    expect(
      screen.getByText(/backend routes · 1 graph kind · 1 SOL tool — implemented and reviewed/)
    ).toBeInTheDocument()
  })

  it('says nothing about a backend for a community bundle', () => {
    render(<OverviewTab view={viewOf({ install: {} })} />)
    expect(screen.queryByText(/first-party/)).toBeNull()
  })

  it('lists only the views the manifest declares, plus a permissions summary', () => {
    render(<OverviewTab view={viewOf({ install: {} })} />)
    expect(screen.getByText('Widget')).toBeInTheDocument()
    expect(screen.getByText('Page: BOM')).toBeInTheDocument()
    expect(screen.queryByText(/Window/)).not.toBeInTheDocument()
    expect(screen.getByText('Permissions')).toBeInTheDocument()
    expect(screen.getByText('2 scopes · 1 network origin')).toBeInTheDocument()
    expect(screen.queryByText('SOL grounding')).not.toBeInTheDocument()
  })

  it('reports project activity honestly by install state', () => {
    const { rerender } = render(<OverviewTab view={viewOf({ install: {} })} />)
    expect(screen.getByText('IDLE')).toBeInTheDocument()
    expect(screen.getByText('No activity in this project yet.')).toBeInTheDocument()
    rerender(<OverviewTab view={viewOf({ install: { enabled: false } })} />)
    expect(screen.getByText('DISABLED')).toBeInTheDocument()
    rerender(
      <OverviewTab
        view={viewOf({
          install: { enabled: false, policy: { blocked: true, default_installed: false } }
        })}
      />
    )
    expect(screen.getByText('BLOCKED BY TEAM')).toBeInTheDocument()
    rerender(<OverviewTab view={viewOf()} />)
    expect(screen.getByText('NOT INSTALLED')).toBeInTheDocument()
  })

  it('shows requirements with their met/unmet state', () => {
    const cadOrEda = manifest({
      extension: { ...manifest().extension, requires: [['cad', 'eda']] }
    })
    const { rerender } = render(<OverviewTab view={viewOf({ manifest: cadOrEda })} />)
    const req = screen.getByTestId('detail-requires')
    expect(req).toHaveTextContent('A CAD source (Onshape) or An EDA source (KiCad, Altium)')
    expect(req.querySelector('[data-met="false"]')).not.toBeNull()
    rerender(<OverviewTab view={viewOf({ manifest: cadOrEda, connected: ['eda'] })} />)
    expect(screen.getByTestId('detail-requires').querySelector('[data-met="true"]')).not.toBeNull()
    rerender(
      <OverviewTab
        view={viewOf({
          manifest: manifest({ extension: { ...manifest().extension, requires: [] } })
        })}
      />
    )
    expect(screen.getByText('No connected source required.')).toBeInTheDocument()
  })

  it('shows unmetered credits and the manifest links, opening outside the app', () => {
    render(<OverviewTab view={viewOf({ install: {} })} />)
    expect(screen.getByText('This cycle')).toBeInTheDocument()
    // Unmetered until the backend reports spend — never a fabricated zero.
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('Per run, typical')).not.toBeInTheDocument()
    const docs = screen.getByRole('link', { name: /Documentation/ })
    expect(docs).toHaveAttribute('href', 'https://docs.solusforge.com/extensions/bom')
    expect(docs).toHaveAttribute('target', '_blank')
    expect(docs).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('link', { name: /Report an issue/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Terms/ })).not.toBeInTheDocument()
  })

  it('drops a link that is not https instead of rendering it', () => {
    const m = manifest({
      store: {
        ...manifest().store,
        links: { documentation: 'javascript:alert(1)', terms: 'https://ok.example' }
      }
    })
    render(<OverviewTab view={viewOf({ manifest: m, install: {} })} />)
    expect(screen.queryByRole('link', { name: /Documentation/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Terms/ })).toHaveAttribute(
      'href',
      'https://ok.example'
    )
  })

  it('falls back to the catalog view kinds while the manifest loads', () => {
    const view = { ...viewOf({ catalog: { views: ['widget'] } }), manifest: null }
    render(<OverviewTab view={view} />)
    expect(screen.getByText('Widget')).toBeInTheDocument()
    expect(screen.queryByText('Permissions')).not.toBeInTheDocument()
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
  })
})
