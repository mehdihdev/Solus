import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CodeEnvironmentCard, parseCodeEnvironment } from './CodeEnvironmentCard'

const VENV = {
  type: 'venv',
  name: 'firmware-tools',
  path: '/home/dev/robot/.venv',
  interpreter: '/home/dev/robot/.venv/bin/python3.12',
  image: null,
  packages: [
    { name: 'numpy', version: '2.1.0' },
    { name: 'pyserial', version: '3.5' },
    { name: 'local-lib', version: null }
  ],
  detected_on: { os: 'linux', arch: 'x86_64' },
  provenance: 'detected',
  captured_at: '2026-09-07T10:00:00Z'
}

describe('parseCodeEnvironment', () => {
  it('accepts the API payload and normalises optional fields', () => {
    const env = parseCodeEnvironment(VENV)
    expect(env?.name).toBe('firmware-tools')
    expect(env?.packages[2]).toEqual({ name: 'local-lib', version: null })
    expect(env?.detected_on).toEqual({ os: 'linux', arch: 'x86_64' })
  })

  it('rejects anything that is not a CodeEnvironment', () => {
    expect(parseCodeEnvironment(null)).toBeNull()
    expect(parseCodeEnvironment('venv')).toBeNull()
    expect(parseCodeEnvironment({ ...VENV, packages: 'many' })).toBeNull()
    expect(parseCodeEnvironment({ ...VENV, packages: [{ version: '1' }] })).toBeNull()
    expect(parseCodeEnvironment({ ...VENV, provenance: 'guessed' })).toBeNull()
    expect(parseCodeEnvironment({ ...VENV, name: 7 })).toBeNull()
  })
})

describe('CodeEnvironmentCard', () => {
  it('renders the fixture compactly with an expandable package list', () => {
    const { container } = render(<CodeEnvironmentCard payload={VENV} />)
    expect(screen.getByText('venv')).toBeInTheDocument()
    expect(screen.getByText('firmware-tools')).toBeInTheDocument()
    expect(screen.getByText(/\.venv\/bin\/python3\.12/)).toBeInTheDocument()
    expect(screen.getByText('detected')).toBeInTheDocument()
    expect(screen.getByText(/linux\/x86_64/)).toBeInTheDocument()
    expect(container.querySelector('time')?.getAttribute('datetime')).toBe('2026-09-07T10:00:00Z')
    expect(screen.queryByText('numpy')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /3 packages/ }))
    expect(screen.getByText('numpy')).toBeInTheDocument()
    expect(screen.getByText('2.1.0')).toBeInTheDocument()
    expect(screen.getByText('local-lib')).toBeInTheDocument()
  })

  it('shows the image for container environments and maps provenance to a chip', () => {
    render(
      <CodeEnvironmentCard
        payload={{
          type: 'docker',
          name: 'ros-humble',
          image: 'ros:humble-ros-base',
          packages: [],
          provenance: 'user'
        }}
      />
    )
    expect(screen.getByText('ros:humble-ros-base')).toBeInTheDocument()
    expect(screen.getByText('you')).toBeInTheDocument()
    expect(screen.getByText('0 packages')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('labels a SOL-authored environment "sol"', () => {
    render(<CodeEnvironmentCard payload={{ ...VENV, provenance: 'sol' }} />)
    expect(screen.getByText('sol')).toBeInTheDocument()
  })

  it('degrades a malformed payload to one honest line', () => {
    render(<CodeEnvironmentCard payload={{ type: 'venv' }} />)
    expect(screen.getByText('environment (unreadable)')).toBeInTheDocument()
    expect(screen.queryByText('venv')).not.toBeInTheDocument()
  })
})
