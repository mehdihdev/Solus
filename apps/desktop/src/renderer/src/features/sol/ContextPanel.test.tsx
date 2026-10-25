// SOLUSDEV-233: the CONTEXT IN USE panel — the last turn's context manifest (files +
// graph chips, labels only). The custom instruction card has its own test.
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ContextPanel } from './ContextPanel'
import { citationLabel } from './citationLabel'
import type { ContextUsedInfo } from './solStream'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSettings: vi.fn(), updateCustomInstruction: vi.fn() }
})
const getSettings = vi.mocked(resources.getSettings)

const SETTINGS: resources.UserSettings = {
  sol_mode: 'guide',
  sol_custom_instruction: null,
  data_collection_consent: false,
  onboarding_step: 'done'
}

const CONTEXT: ContextUsedInfo = {
  sections: [
    { kind: 'document', citation: '[datasheet:so101.urdf]', tokens: 200 },
    { kind: 'document', citation: '[github:act_policy.py]', tokens: 150 },
    { kind: 'graph', citation: '[graph:motor_driver]', tokens: 80 },
    // The backend's graph floor carries NO citation (context.py _graph_section)
    // — the panel must still show it (security review M2).
    { kind: 'graph', citation: null, tokens: 60 },
    { kind: 'telemetry', citation: null, tokens: 40 }
  ],
  truncated: true,
  dropped: 3
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  getSettings.mockResolvedValue(SETTINGS)
})

describe('citationLabel', () => {
  it('strips the [connector:ref] wrapper to the ref', () => {
    expect(citationLabel('[datasheet:so101.urdf]')).toBe('so101.urdf')
    expect(citationLabel('plain')).toBe('plain')
  })
})

describe('ContextPanel', () => {
  it('renders files, graph chips, and the truncation footnote from the manifest', () => {
    render(<ContextPanel contextUsed={CONTEXT} />)
    expect(screen.getByText('so101.urdf')).toBeInTheDocument()
    expect(screen.getByText('act_policy.py')).toBeInTheDocument()
    expect(screen.getByText('motor_driver')).toBeInTheDocument()
    // An uncited graph section (the backend's graph floor) still shows —
    // a grounding panel that hides the graph misrepresents grounding.
    expect(screen.getByText('graph context ×1')).toBeInTheDocument()
    expect(screen.getByText(/1 telemetry\/error section/)).toBeInTheDocument()
    expect(screen.getByText(/truncated to budget/)).toBeInTheDocument()
  })

  it('lists the screen read as its own tentative line with its token count (SOLUSDEV-252)', () => {
    render(
      <ContextPanel
        contextUsed={{
          ...CONTEXT,
          sections: [...CONTEXT.sections, { kind: 'screen', citation: null, tokens: 412 }]
        }}
      />
    )
    expect(screen.getByText('Screen (tentative read)')).toBeInTheDocument()
    expect(screen.getByText('412 tokens')).toBeInTheDocument()
    // Not folded into the telemetry/error footnote count.
    expect(screen.getByText(/1 telemetry\/error section/)).toBeInTheDocument()
  })

  it('shows an honest empty state before the first turn', () => {
    render(<ContextPanel contextUsed={null} />)
    expect(screen.getByText(/Send a message and SOL will show/)).toBeInTheDocument()
  })
})
