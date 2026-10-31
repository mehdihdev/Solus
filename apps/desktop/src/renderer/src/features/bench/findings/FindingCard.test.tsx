// SOLUSDEV-321 P2-T7 — one finding: headline, the narration as TEXT (never markup), and on
// click the latest evidence (top-level keys, latest-wins — never `items[-1]`), the ranked causes
// and the code site; Resolve offers the code site as the fix only when the person ticks it.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Finding } from '../../../lib/api/findings'
import { useSettingsStore } from '../../../store/settingsStore'
import * as actions from './findingActions'
import { FindingCard } from './FindingCard'

vi.mock('./findingActions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./findingActions')>()),
  explainFinding: vi.fn(),
  proposeFindingFix: vi.fn(),
  openFindingCodeSite: vi.fn(),
  fileFinding: vi.fn(),
  dismissBenchFinding: vi.fn(),
  resolveBenchFinding: vi.fn()
}))

const CODE = '3f1c2b4a-5d6e-4f70-8a9b-0c1d2e3f4a5b'
const SOURCE = '7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d'
const HOSTILE_EXPLANATION = '<img src=x onerror="alert(1)">The rail sagged <b>with</b> the stall.'
const DETAIL =
  'suggested headline: <script>steal()</script> servo 3 stalled\nnot grounded: It drew 9 A.'

const finding = (over: Partial<Finding> = {}): Finding => ({
  id: 'f1',
  rule_id: 'tracking_error_stall',
  severity: 'critical',
  source: 'observer',
  status: 'open',
  headline: 'servo 3 (joint 3) stalls at 12.0 deg against a 40.0 deg command',
  explanation: HOSTILE_EXPLANATION,
  detail: DETAIL,
  causes_ranked: ['power_supply', 'mechanical_load'],
  subjects: ['e1'],
  evidence: {
    current_a: 2.4,
    bounds_source: 'config',
    unit: 'deg',
    robot_id: 'r1',
    session_id: 's1',
    also: ['current_over_rating'],
    code_site: { entity_id: CODE, source_id: SOURCE, path: 'fw/fake_arm.ino', line: 13 },
    causes: [
      { kind: 'mechanical_load', for: ['position held 1.2 s'], against: [] },
      { kind: 'power_supply', for: ['rail sagged at the peak'], against: ['no brownout reset'] }
    ],
    items: [{ current_a: 9.9 }]
  },
  count: 4,
  first_seen: '2026-10-27T10:00:05+00:00',
  last_seen: '2026-10-27T10:00:09+00:00',
  matrix_cell: null,
  domain: 'electrical',
  dismissed_until: null,
  created_at: '',
  updated_at: '',
  ...over
})

beforeEach(() => {
  vi.clearAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('FindingCard', () => {
  it('explanation renders as text', () => {
    const { container } = render(
      <FindingCard projectId="p1" finding={finding()} onChanged={vi.fn()} />
    )
    expect(screen.getByText(HOSTILE_EXPLANATION)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /servo 3 \(joint 3\) stalls/ }))
    // `detail` is lines of text: each line is its own text node, nothing is parsed into markup.
    expect(
      screen.getByText('suggested headline: <script>steal()</script> servo 3 stalled')
    ).toBeInTheDocument()
    expect(screen.getByText('not grounded: It drew 9 A.')).toBeInTheDocument()
    expect(container.querySelector('img, script, b')).toBeNull()
  })

  it('keeps the explanation behind the click in Expert mode', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<FindingCard projectId="p1" finding={finding()} onChanged={vi.fn()} />)
    expect(screen.queryByText(HOSTILE_EXPLANATION)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /servo 3 \(joint 3\) stalls/ }))
    expect(screen.getByText(HOSTILE_EXPLANATION)).toBeInTheDocument()
  })

  it('shows the latest evidence, the ranked causes and the code site on click', () => {
    render(<FindingCard projectId="p1" finding={finding()} onChanged={vi.fn()} />)
    expect(screen.queryByText('fw/fake_arm.ino:13')).not.toBeInTheDocument()
    expect(screen.getByText(/×4/)).toBeInTheDocument()
    expect(screen.getByText(/last seen/).querySelector('time')).toHaveAttribute(
      'datetime',
      '2026-10-27T10:00:09+00:00'
    )
    fireEvent.click(screen.getByRole('button', { name: /servo 3 \(joint 3\) stalls/ }))
    const evidence = screen.getByRole('list', { name: 'Evidence' })
    expect(within(evidence).getByText('current a')).toBeInTheDocument()
    expect(within(evidence).getByText('2.4')).toBeInTheDocument()
    expect(within(evidence).queryByText('9.9')).not.toBeInTheDocument()
    expect(within(evidence).queryByText('robot id')).not.toBeInTheDocument()
    const causes = within(screen.getByRole('list', { name: 'Likely causes' })).getAllByRole(
      'listitem'
    )
    expect(causes.map((item) => item.textContent)).toEqual([
      expect.stringMatching(/^power supply.*rail sagged at the peak.*no brownout reset/),
      expect.stringMatching(/^mechanical load.*position held 1\.2 s/)
    ])
    expect(screen.getByText('fw/fake_arm.ino:13')).toBeInTheDocument()
    expect(screen.getByText(/current_over_rating/)).toBeInTheDocument()
  })

  it('opens already expanded when a marker opened it', () => {
    render(<FindingCard projectId="p1" finding={finding()} defaultOpen onChanged={vi.fn()} />)
    expect(screen.getByRole('list', { name: 'Evidence' })).toBeInTheDocument()
  })
})

describe('FindingCard resolve', () => {
  it('Resolve with note sends the code site as the fix only when ticked', async () => {
    const onChanged = vi.fn()
    vi.mocked(actions.resolveBenchFinding).mockResolvedValue(finding({ status: 'resolved' }))
    render(<FindingCard projectId="p1" finding={finding()} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('button', { name: 'Resolve with note' }))
    const submit = screen.getByRole('button', { name: 'Resolve' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Resolution note'), {
      target: { value: 'Replaced the cracked horn' }
    })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Fixed in fw/fake_arm.ino:13' }))
    fireEvent.click(submit)
    await waitFor(() =>
      expect(actions.resolveBenchFinding).toHaveBeenCalledExactlyOnceWith(
        'p1',
        expect.objectContaining({ id: 'f1' }),
        'Replaced the cracked horn',
        CODE
      )
    )
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
  })

  it('offers no fix box and no Open the tool without a usable code site', () => {
    render(
      <FindingCard
        projectId="p1"
        finding={finding({ evidence: { current_a: 2.4 } })}
        onChanged={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'Open the tool' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resolve with note' }))
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
