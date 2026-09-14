// SOLUS-TU-09 — the Guide side-panel.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { GuidePanel } from './GuidePanel'
import * as guideApi from './guideApi'
import type { GuideDetail, GuideStepView } from './guideApi'
import * as useGuideMod from './useGuide'
import { useSettingsStore } from '../../store/settingsStore'

vi.mock('./useGuide', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useGuide')>()
  return { ...actual, useGuide: vi.fn() }
})
vi.mock('./guideApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./guideApi')>()
  return { ...actual, sendFeedback: vi.fn() }
})

function step(over: Partial<GuideStepView> = {}): GuideStepView {
  return {
    step_number: 1,
    control_id: 'kicad.eeschema.interactive_drawing.place_label',
    entry_id: '00000000-0000-0000-0000-0000000000ab',
    note_guide: 'Give the net a name with a net label.',
    note_expert: 'Label the net.',
    available: true,
    tentative: false,
    stale: false,
    label: 'Place Net Labels',
    description: 'Places a named net label.',
    shortcut: 'L',
    menu_path: null,
    surface: 'keyboard',
    confidence: 0.8,
    locator: null, // the panel ignores geometry; the overlay is the consumer
    ...over
  }
}

const DETAIL: GuideDetail = {
  id: 'kicad.eeschema.first_schematic',
  tool: 'kicad',
  title: 'Wire up your first schematic',
  summary: 'The core loop of drawing a schematic.',
  steps: [step()]
}

function mockGuide(state: Partial<useGuideMod.GuideState>): void {
  vi.mocked(useGuideMod.useGuide).mockReturnValue({
    status: 'ready',
    guide: DETAIL,
    ...state
  } as useGuideMod.GuideState)
}

beforeEach(() => {
  vi.clearAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GuidePanel', () => {
  registerGuidePresentationTests()

  registerGuideFeedbackTests()
})

function registerGuidePresentationTests(): void {
  it('renders the walkthrough title and ordered steps', () => {
    mockGuide({})
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.getByText('Wire up your first schematic')).toBeInTheDocument()
    expect(screen.getByText('Place Net Labels')).toBeInTheDocument()
    expect(screen.getByText(/Give the net a name/)).toBeInTheDocument()
    // invocation surfaced — the shortcut key in its own <kbd>
    expect(screen.getByText('L')).toBeInTheDocument()
    expect(screen.getByText(/Shortcut:/)).toBeInTheDocument()
  })

  it('respects SOL Expert mode (ADR-016)', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    mockGuide({})
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.getByText('Label the net.')).toBeInTheDocument()
    expect(screen.queryByText(/Give the net a name/)).not.toBeInTheDocument()
  })

  it('marks a low-confidence step tentative, never a confident instruction', () => {
    mockGuide({ guide: { ...DETAIL, steps: [step({ tentative: true, confidence: 0.4 })] } })
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.getByText(/tentative|not sure|unverified/i)).toBeInTheDocument()
  })

  it('degrades a step the KB does not cover — shows narration, no fake pointer', () => {
    mockGuide({
      guide: {
        ...DETAIL,
        steps: [
          step({
            available: false,
            label: null,
            description: null,
            shortcut: null,
            confidence: null
          })
        ]
      }
    })
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    // the authored narration still renders (graceful degradation)
    expect(screen.getByText(/Give the net a name/)).toBeInTheDocument()
    // but no confident control label/shortcut is shown for it
    expect(screen.queryByText('Place Net Labels')).not.toBeInTheDocument()
    expect(screen.getByText(/knowledge base/i)).toBeInTheDocument()
  })

  it('shows a loading state', () => {
    mockGuide({ status: 'loading', guide: null })
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows an honest empty state on error', () => {
    mockGuide({ status: 'error', guide: null })
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.getByText(/couldn.t load|unavailable|try again/i)).toBeInTheDocument()
  })
}

function registerGuideFeedbackTests(): void {
  it('sends a reject to the step entry and confirms it landed (TU-08)', async () => {
    vi.mocked(guideApi.sendFeedback).mockResolvedValue({
      id: 'x',
      confidence: 0.27,
      confirm_count: 0,
      reject_count: 1
    })
    mockGuide({})
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    fireEvent.click(screen.getByText('Wrong'))
    expect(guideApi.sendFeedback).toHaveBeenCalledWith(
      '00000000-0000-0000-0000-0000000000ab',
      'reject'
    )
    await waitFor(() => expect(screen.getByText(/flagged for review/i)).toBeInTheDocument())
  })

  it('offers no feedback control for a step the KB does not cover', () => {
    mockGuide({
      guide: { ...DETAIL, steps: [step({ available: false, entry_id: null, label: null })] }
    })
    render(<GuidePanel guideId="g1" tool="kicad" version="9.0.4" />)
    expect(screen.queryByText('Helpful')).not.toBeInTheDocument()
  })
}
