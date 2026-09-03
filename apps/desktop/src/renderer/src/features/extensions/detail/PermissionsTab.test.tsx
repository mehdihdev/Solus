// SOLUSDEV-235 — detail › Permissions.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PermissionsTab } from './PermissionsTab'
import { EXTENSION_CATALOG } from '../extensions.catalog'
import { buildView, DEFAULT_INSTALL_STATE } from '../extensionLogic'
import type { ExtensionManifest, ExtensionView } from '../extension.types'

function viewOf(manifest: ExtensionManifest): ExtensionView {
  return buildView(manifest, { ...DEFAULT_INSTALL_STATE, installed: true }, new Set())
}

const experiments = EXTENSION_CATALOG.find((m) => m.id === 'experiments')!

describe('PermissionsTab', () => {
  it('lists each scope with its grant status', () => {
    render(<PermissionsTab view={viewOf(experiments)} />)
    expect(screen.getByText('Read the context graph')).toBeInTheDocument()
    expect(screen.getByText('Entity names, relations, units')).toBeInTheDocument()
    expect(screen.getByText('GRANTED')).toBeInTheDocument()
    expect(screen.getByText('Read telemetry streams')).toBeInTheDocument()
    expect(screen.getByText('Not yet requested')).toBeInTheDocument()
    expect(screen.getByText('NOT ASKED')).toBeInTheDocument()
  })

  it('says scopes are declared by the extension and enforced server-side, not granted here', () => {
    render(<PermissionsTab view={viewOf(experiments)} />)
    expect(screen.getByText(/scopes the extension declares/)).toBeInTheDocument()
    expect(screen.getByText(/enforces scopes server-side/)).toBeInTheDocument()
  })

  it('states the hardware-write guarantee', () => {
    render(<PermissionsTab view={viewOf(experiments)} />)
    expect(screen.getByText(/never write to hardware directly/)).toBeInTheDocument()
    expect(screen.getByText(/approval queue/)).toBeInTheDocument()
  })

  it('handles an extension that asks for nothing', () => {
    render(<PermissionsTab view={viewOf({ ...experiments, permissions: [] })} />)
    expect(screen.getByText('This extension asks for no permissions.')).toBeInTheDocument()
  })
})
