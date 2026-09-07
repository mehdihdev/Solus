// SOLUSDEV-250 (I3) — the dialog's section components on their own: the
// default interpreter is not repeated in the "other interpreters" list, a
// requirement without a specifier is a bare name, and a section staggers its
// entrance by index.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CodeProbe } from '../../lib/api/resources.codeenv'
import { SECTION_STAGGER_MS } from '../project/codeEnvironment.constants'
import { InterpreterSection, ProposalSection, Section } from './CodeEnvironmentSections'

const PROBE: CodeProbe = {
  python: { path: '/usr/bin/python3', version: '3.12.4' },
  interpreters: [
    { path: '/usr/bin/python3', version: '3.12.4' },
    { path: '/usr/local/bin/python3.11', version: '3.11.9' }
  ],
  venv: null,
  conda: null,
  uv: null
}

describe('InterpreterSection', () => {
  it('lists the default python once, then the others', () => {
    render(<InterpreterSection probe={PROBE} />)
    expect(screen.getAllByText('/usr/bin/python3')).toHaveLength(1)
    expect(screen.getByText('/usr/local/bin/python3.11')).toBeInTheDocument()
  })
})

describe('ProposalSection', () => {
  it('renders a requirement without a specifier as its bare name', () => {
    render(
      <ProposalSection
        requirementCount={1}
        proposal={{
          split: false,
          environments: [
            {
              name: 'default',
              source_files: ['requirements.txt'],
              requirements: [{ name: 'numpy', specifier: '', source_file: 'requirements.txt' }]
            }
          ]
        }}
      />
    )
    expect(screen.getByText('numpy')).toBeInTheDocument()
    expect(screen.getByText('1 requirement')).toBeInTheDocument()
  })
})

describe('Section', () => {
  it('staggers by index', () => {
    render(
      <Section title="Conflicts" index={3}>
        <span>body</span>
      </Section>
    )
    const region = screen.getByRole('region', { name: 'Conflicts' })
    expect(region).toHaveStyle({ animationDelay: `${3 * SECTION_STAGGER_MS}ms` })
  })
})
