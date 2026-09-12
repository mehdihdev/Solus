// SOLUSDEV-235 — detail › Permissions, read from the install row's grants.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PermissionsTab } from './PermissionsTab'
import { manifest, viewOf } from '../testing/fixtures'

describe('PermissionsTab', () => {
  it('lists each declared scope with GRANTED from the install row', () => {
    render(<PermissionsTab view={viewOf({ install: {} })} />)
    expect(screen.getByText('Read the workspace graph')).toBeInTheDocument()
    expect(screen.getByText('List connected sources')).toBeInTheDocument()
    expect(screen.getAllByText('GRANTED')).toHaveLength(3)
    expect(screen.getByText('https://api.octopart.com')).toBeInTheDocument()
    expect(screen.queryByText('NOT ASKED')).not.toBeInTheDocument()
  })

  it('marks a scope the user has not granted as NOT GRANTED', () => {
    render(
      <PermissionsTab
        view={viewOf({ install: { granted_scopes: ['graph.read'], granted_network: [] } })}
      />
    )
    expect(screen.getAllByText('GRANTED')).toHaveLength(1)
    expect(screen.getAllByText('NOT GRANTED')).toHaveLength(2)
  })

  it('shows every scope as NOT GRANTED before an install', () => {
    render(<PermissionsTab view={viewOf()} />)
    expect(screen.getAllByText('NOT GRANTED')).toHaveLength(3)
  })

  it('says grants are per project and enforced by Solus', () => {
    render(<PermissionsTab view={viewOf({ install: {} })} />)
    expect(screen.getByText(/per project/)).toBeInTheDocument()
    expect(screen.getByText(/enforces .* at every call/)).toBeInTheDocument()
  })

  it('states the hardware-write guarantee', () => {
    render(<PermissionsTab view={viewOf({ install: {} })} />)
    expect(screen.getByText(/never write to hardware directly/)).toBeInTheDocument()
    expect(screen.getByText(/approval queue/)).toBeInTheDocument()
  })

  it('handles an extension that asks for nothing', () => {
    render(
      <PermissionsTab
        view={viewOf({ manifest: manifest({ permissions: { scopes: [], network: [] } }) })}
      />
    )
    expect(screen.getByText('This extension asks for no permissions.')).toBeInTheDocument()
  })

  it('says it is loading before the manifest arrives', () => {
    render(<PermissionsTab view={{ ...viewOf(), manifest: null }} />)
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
  })
})
