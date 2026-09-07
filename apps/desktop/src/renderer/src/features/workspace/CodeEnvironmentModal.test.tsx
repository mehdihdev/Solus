// SOLUSDEV-250 (I3) — the Code environment details dialog: every section says
// what the probe and the graph actually found — "not found" is a finding —
// conflicts quote the checker's message verbatim with its pins, the proposal
// is one card per environment (or "Single environment"), and the footer hands
// the setup off to SOL.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import {
  EMPTY_CODE_ENVIRONMENT_VIEW,
  type CheckerWarning,
  type CodeEnvironmentView,
  type CodeProbe
} from '../../lib/api/resources.codeenv'
import { NO_REQUIREMENTS_TEXT } from '../project/codeEnvironment.constants'
import { CodeEnvironmentModal } from './CodeEnvironmentModal'

const PROBE: CodeProbe = {
  python: { path: '/usr/bin/python3', version: '3.12.4' },
  interpreters: [
    { path: '/usr/bin/python3', version: '3.12.4' },
    { path: '/opt/homebrew/bin/python3.11', version: '3.11.9' }
  ],
  venv: {
    path: '.venv',
    python_version: '3.12.4',
    packages: [
      { name: 'torch', version: '2.1.0' },
      { name: 'numpy', version: '1.26.4' }
    ],
    truncated: false
  },
  conda: { path: '/opt/conda', envs: ['base', 'isaac'] },
  uv: { path: '/opt/homebrew/bin/uv', version: '0.4.0' }
}

const CONFLICT: CheckerWarning = {
  checker_id: 'pin_conflict',
  severity: 'warning',
  message: 'torch is pinned ==2.1.0 in isaac/requirements.txt and >=2.3 in policy/pyproject.toml',
  evidence: {
    package: 'torch',
    pins: [
      { specifier: '==2.1.0', source_file: 'isaac/requirements.txt' },
      { specifier: '>=2.3', source_file: 'policy/pyproject.toml' }
    ]
  },
  suggested_area: 'code'
}

const SPLIT: CodeEnvironmentView = {
  ...EMPTY_CODE_ENVIRONMENT_VIEW,
  bridge: { connected: true, code_server: true },
  probe: PROBE,
  requirements: { count: 3, files: ['isaac/requirements.txt', 'policy/pyproject.toml'] },
  conflicts: [CONFLICT],
  proposal: {
    environments: [
      {
        name: 'isaac',
        source_files: ['isaac/requirements.txt'],
        requirements: [
          { name: 'torch', specifier: '==2.1.0', source_file: 'isaac/requirements.txt' }
        ]
      },
      {
        name: 'policy',
        source_files: ['policy/pyproject.toml'],
        requirements: [
          { name: 'torch', specifier: '>=2.3', source_file: 'policy/pyproject.toml' },
          { name: 'numpy', specifier: '', source_file: 'policy/pyproject.toml' }
        ]
      }
    ],
    split: true
  }
}

function section(name: string): HTMLElement {
  return screen.getByRole('region', { name })
}

describe('CodeEnvironmentModal — sections', () => {
  it('INTERPRETER lists python, every interpreter, and uv/conda presence', () => {
    render(<CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />)
    const s = section('Interpreter')
    expect(within(s).getByText('3.12.4')).toBeInTheDocument()
    expect(within(s).getByText('/usr/bin/python3')).toBeInTheDocument()
    expect(within(s).getByText('/opt/homebrew/bin/python3.11')).toBeInTheDocument()
    expect(within(s).getByText('3.11.9')).toBeInTheDocument()
    expect(within(s).getByText('uv 0.4.0')).toBeInTheDocument()
    expect(within(s).getByText('conda · 2 envs')).toBeInTheDocument()
  })

  it('INTERPRETER calls a missing python, uv and conda "not found", and no probe "not probed yet"', () => {
    const view = { ...SPLIT, probe: { ...PROBE, python: null, uv: null, conda: null } }
    const { rerender } = render(
      <CodeEnvironmentModal view={view} onClose={vi.fn()} onAskSol={vi.fn()} />
    )
    let s = section('Interpreter')
    expect(within(s).getByText('no Python found')).toBeInTheDocument()
    expect(within(s).getByText('uv not found')).toBeInTheDocument()
    expect(within(s).getByText('conda not found')).toBeInTheDocument()

    rerender(
      <CodeEnvironmentModal view={{ ...SPLIT, probe: null }} onClose={vi.fn()} onAskSol={vi.fn()} />
    )
    s = section('Interpreter')
    expect(within(s).getByText('not probed yet')).toBeInTheDocument()
    expect(within(section('Virtual environment')).getByText('not probed yet')).toBeInTheDocument()
  })

  it('VIRTUAL ENVIRONMENT shows path, python and the package count, with "and N more" when cut', () => {
    const { rerender } = render(
      <CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />
    )
    let s = section('Virtual environment')
    expect(within(s).getByText('.venv')).toBeInTheDocument()
    expect(within(s).getByText('Python 3.12.4')).toBeInTheDocument()
    expect(within(s).getByText('2 packages')).toBeInTheDocument()
    expect(within(s).getByText('torch 2.1.0')).toBeInTheDocument()
    expect(within(s).queryByText(/and .* more/)).toBeNull()

    const truncated = { ...SPLIT, probe: { ...PROBE, venv: { ...PROBE.venv!, truncated: true } } }
    rerender(<CodeEnvironmentModal view={truncated} onClose={vi.fn()} onAskSol={vi.fn()} />)
    s = section('Virtual environment')
    expect(within(s).getByText('2 packages listed, and more')).toBeInTheDocument()

    rerender(
      <CodeEnvironmentModal
        view={{ ...SPLIT, probe: { ...PROBE, venv: null } }}
        onClose={vi.fn()}
        onAskSol={vi.fn()}
      />
    )
    expect(
      within(section('Virtual environment')).getByText('no virtual environment')
    ).toBeInTheDocument()
  })

  it('REQUIREMENTS shows the count and each file as a mono chip', () => {
    render(<CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />)
    const s = section('Requirements')
    expect(within(s).getByText('3 requirements')).toBeInTheDocument()
    expect(within(s).getByText('isaac/requirements.txt')).toBeInTheDocument()
    expect(within(s).getByText('policy/pyproject.toml')).toBeInTheDocument()
  })
})

describe('CodeEnvironmentModal — conflicts and proposal', () => {
  it('CONFLICTS quotes the message verbatim in red with its pins', () => {
    render(<CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />)
    const s = section('Conflicts')
    const message = within(s).getByText(CONFLICT.message)
    expect(message).toHaveStyle({ color: 'var(--err)' })
    expect(within(s).getByText('==2.1.0 · isaac/requirements.txt')).toBeInTheDocument()
    expect(within(s).getByText('>=2.3 · policy/pyproject.toml')).toBeInTheDocument()
  })

  it('CONFLICTS says none when the graph found none', () => {
    render(
      <CodeEnvironmentModal
        view={{ ...SPLIT, conflicts: [] }}
        onClose={vi.fn()}
        onAskSol={vi.fn()}
      />
    )
    expect(within(section('Conflicts')).getByText('No conflicts found.')).toBeInTheDocument()
  })

  it('PROPOSAL is one card per environment when split: name, files, requirement chips', () => {
    render(<CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />)
    const s = section('Proposal')
    expect(within(s).getByText('Split into 2 environments')).toBeInTheDocument()
    const isaac = within(s).getByTestId('proposal-isaac')
    expect(within(isaac).getByText('isaac')).toBeInTheDocument()
    expect(within(isaac).getByText('isaac/requirements.txt')).toBeInTheDocument()
    expect(within(isaac).getByText('torch==2.1.0')).toBeInTheDocument()
    const policy = within(s).getByTestId('proposal-policy')
    expect(within(policy).getByText('torch>=2.3')).toBeInTheDocument()
    expect(within(policy).getByText('numpy')).toBeInTheDocument()
  })

  it('PROPOSAL says "Single environment" when nothing splits', () => {
    const single: CodeEnvironmentView = {
      ...SPLIT,
      conflicts: [],
      proposal: {
        environments: [
          {
            name: 'default',
            source_files: ['requirements.txt'],
            requirements: [{ name: 'numpy', specifier: '', source_file: 'requirements.txt' }]
          }
        ],
        split: false
      }
    }
    render(<CodeEnvironmentModal view={single} onClose={vi.fn()} onAskSol={vi.fn()} />)
    const s = section('Proposal')
    expect(within(s).getByText('Single environment')).toBeInTheDocument()
    expect(within(s).getByTestId('proposal-default')).toBeInTheDocument()
  })

  it('PROPOSAL shows the empty state when the folder has no requirement files', () => {
    const empty: CodeEnvironmentView = {
      ...SPLIT,
      conflicts: [],
      requirements: { count: 0, files: [] },
      proposal: null
    }
    render(<CodeEnvironmentModal view={empty} onClose={vi.fn()} onAskSol={vi.fn()} />)
    expect(within(section('Proposal')).getByText(NO_REQUIREMENTS_TEXT)).toBeInTheDocument()
    expect(within(section('Requirements')).getByText('0 requirements')).toBeInTheDocument()
  })
})

describe('CodeEnvironmentModal — footer', () => {
  it('Ask SOL to set it up hands off; the X closes', async () => {
    const onAskSol = vi.fn()
    const onClose = vi.fn()
    render(<CodeEnvironmentModal view={SPLIT} onClose={onClose} onAskSol={onAskSol} />)
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL to set it up' }))
    expect(onAskSol).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('Ask SOL is disabled without a proposal — there is nothing to set up', () => {
    const view = { ...SPLIT, requirements: { count: 0, files: [] }, proposal: null }
    render(<CodeEnvironmentModal view={view} onClose={vi.fn()} onAskSol={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Ask SOL to set it up' })).toBeDisabled()
  })

  it('sections enter with the shared fade-rise', () => {
    render(<CodeEnvironmentModal view={SPLIT} onClose={vi.fn()} onAskSol={vi.fn()} />)
    expect(section('Interpreter')).toHaveClass('code-env-in')
  })
})
