// SOLUSDEV-233: the CONTEXT IN USE panel — the last turn's context manifest (files +
// graph chips, labels only). The custom instruction card has its own test.
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
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
  useFocusStore.getState().reset()
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

// SOLUSDEV-321 P1-T6: "Why SOL looked here" — where the turn was pointed and what each layer cost,
// in the server's own words and order. Nothing here is written by the client but the layout.
const FOCUSED = '0f9c2f2a-1111-4222-8333-444455556666'
const PINNED = 'aaaaaaaa-1111-4222-8333-444455557777'
const LOST = 'bbbbbbbb-1111-4222-8333-444455558888'
const WHY: ContextUsedInfo = {
  ...CONTEXT,
  layers: [
    { layer: 'project_card', tokens: 60, emptyReason: null },
    { layer: 'graph', tokens: 120, emptyReason: null },
    { layer: 'findings', tokens: 0, emptyReason: 'no findings in scope' },
    { layer: 'screen', tokens: 0, emptyReason: 'no screenshot on this turn' }
  ],
  anchors: [
    { id: FOCUSED, reason: 'focused' },
    { id: PINNED, reason: 'pinned' }
  ],
  anchorsDropped: [{ id: LOST, reason: 'mentioned', cause: 'not_visible' }]
}

/** The last neighbourhood fetched for p1: the focus cache is where a name can come from. */
function cacheNames(...entities: { id: string; name: string }[]): void {
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' } })
  useFocusStore.setState({
    cache: {
      [`p1:${FOCUSED}@1`]: {
        entities: entities.map((e) => ({
          ...e,
          type: 'motor',
          domain: 'electrical',
          source_key: e.id
        })),
        edges: [],
        truncated: false
      }
    }
  })
}

describe('ContextPanel — Why SOL looked here', () => {
  it('renders anchor reasons and layer tokens', () => {
    cacheNames({ id: FOCUSED, name: 'knee_motor' })
    render(<ContextPanel contextUsed={WHY} />)
    expect(screen.getByText('Why SOL looked here')).toBeInTheDocument()
    // A name when the graph cache has one, else the id's first eight characters.
    expect(screen.getByText('knee_motor — focused')).toBeInTheDocument()
    expect(screen.getByText('aaaaaaaa — pinned')).toBeInTheDocument()
    expect(screen.getByText('bbbbbbbb — dropped (mentioned): not_visible')).toBeInTheDocument()
    // The layers in the server's order, each with the server's reason when it cost nothing.
    const layers = screen.getByRole('list', { name: 'Tokens per layer' })
    expect(
      within(layers)
        .getAllByRole('listitem')
        .map((row) => row.textContent)
    ).toEqual([
      'project_card: 60',
      'graph: 120',
      'findings: 0 — no findings in scope',
      'screen: 0 — no screenshot on this turn'
    ])
  })

  it('never names a dropped anchor — it may be one the caller cannot see', () => {
    cacheNames({ id: LOST, name: 'secret_part' })
    render(<ContextPanel contextUsed={WHY} />)
    expect(screen.getByText('bbbbbbbb — dropped (mentioned): not_visible')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('secret_part')
  })

  it('names an anchor only from the current project’s cache', () => {
    cacheNames({ id: FOCUSED, name: 'knee_motor' })
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
    render(<ContextPanel contextUsed={WHY} />)
    expect(screen.getByText('0f9c2f2a — focused')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('knee_motor')
  })

  it('says so when nothing anchored the turn, and still shows what each layer cost', () => {
    render(<ContextPanel contextUsed={{ ...WHY, anchors: [], anchorsDropped: [] }} />)
    expect(screen.getByText('No anchors — SOL searched the index.')).toBeInTheDocument()
    expect(screen.queryByText(/dropped \(/)).toBeNull()
    expect(screen.getByText('graph: 120')).toBeInTheDocument()
  })

  it('claims nothing for a frame that never said — absent is not "no anchors"', () => {
    render(<ContextPanel contextUsed={CONTEXT} />)
    expect(screen.queryByText('Why SOL looked here')).toBeNull()
    expect(screen.queryByText(/No anchors/)).toBeNull()
    // The manifest cards it always had are still there.
    expect(screen.getByText('so101.urdf')).toBeInTheDocument()
  })
})

describe('ContextPanel — Why SOL looked here, edge cases', () => {
  it('omits a dropped cause the server did not give', () => {
    const dropped = [{ id: LOST, reason: 'pinned', cause: null }]
    render(<ContextPanel contextUsed={{ ...WHY, anchorsDropped: dropped }} />)
    expect(screen.getByText('bbbbbbbb — dropped (pinned)')).toBeInTheDocument()
  })

  it('lists the first five dropped anchors and counts the rest', () => {
    const many = Array.from({ length: 7 }, (_, n) => ({
      id: `${n}0000000-1111-4222-8333-444455558888`,
      reason: 'ref_match',
      cause: 'over_cap'
    }))
    render(<ContextPanel contextUsed={{ ...WHY, anchorsDropped: many }} />)
    expect(screen.getAllByText(/ — dropped \(ref_match\): over_cap/)).toHaveLength(5)
    expect(screen.getByText('+2 more dropped')).toBeInTheDocument()
  })

  it('renders every word as text, never markup', () => {
    const hostile = '<img src=x onerror=alert(1)>'
    render(
      <ContextPanel
        contextUsed={{
          ...WHY,
          anchors: [{ id: PINNED, reason: hostile }],
          layers: [{ layer: hostile, tokens: 0, emptyReason: hostile }]
        }}
      />
    )
    expect(document.querySelector('img, [onerror]')).toBeNull()
    expect(screen.getByText(`aaaaaaaa — ${hostile}`)).toBeInTheDocument()
  })
})
