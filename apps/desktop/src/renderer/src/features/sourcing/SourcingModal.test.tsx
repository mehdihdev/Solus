// SOLUSDEV-246 (STORE ST5) — the sourcing panel: describe or derive, compare,
// exclusions with reasons, select into a category as PLANNED, vendor CAD link.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as resources from '../../lib/api/resources'
import type { SourcingActions, SourcingData } from './useSourcing'
import { SourcingModal } from './SourcingModal'
import { request, rules, torque } from './testing/fixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  listEntities: vi.fn()
}))
vi.mock('./useSourcing', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./useSourcing')>()),
  useSourcing: vi.fn(() => data({}))
}))

function actions(over: Partial<SourcingActions> = {}): SourcingActions {
  return {
    derive: vi.fn(async () => undefined),
    submit: vi.fn(async () => undefined),
    select: vi.fn(async () => undefined),
    saveRules: vi.fn(async () => true),
    reset: vi.fn(),
    ...over
  }
}

function data(over: Partial<SourcingData>): SourcingData {
  return {
    phase: 'requirement',
    rules: rules(),
    torque: null,
    request: null,
    selected: null,
    error: null,
    busy: false,
    actions: actions(),
    ...over
  }
}

const entity = (over: Partial<resources.Entity>): resources.Entity =>
  ({
    id: 'x',
    type: 'part',
    domain: 'mechanical',
    name: 'x',
    source_key: '',
    ...over
  }) as resources.Entity

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(resources.listEntities).mockImplementation(async (_p, filters) => {
    if (filters?.type === 'robot_category')
      return [
        entity({ id: 'cat-wire', type: 'robot_category', name: 'Wiring' }),
        entity({ id: 'cat-act', type: 'robot_category', name: 'Actuators / motors' })
      ]
    return [
      entity({ id: 'asm-1', name: 'Arm assembly', properties: { is_assembly: true } }),
      entity({ id: 'p-1', name: 'Arm link', properties: { is_assembly: false } })
    ]
  })
})

describe('SourcingModal — requirement', () => {
  it('describes a requirement and submits it for the BOM door', async () => {
    const a = actions()
    render(
      <SourcingModal projectId="p1" door="bom" onClose={vi.fn()} sourcing={data({ actions: a })} />
    )
    expect(screen.getByRole('dialog', { name: 'Find a part' })).toBeInTheDocument()
    expect(screen.getByTestId('sourcing-rules-line')).toHaveTextContent(
      'Project rules: 1 excluded supplier · requires RoHS · max 24 V'
    )
    await userEvent.type(screen.getByLabelText('Requirement'), 'holds 2 kg at 30 cm')
    await userEvent.type(screen.getByLabelText('Load (kg)'), '2')
    await userEvent.type(screen.getByLabelText('Arm (m)'), '0.3')
    await userEvent.type(screen.getByLabelText('Protocol'), 'CAN')
    await userEvent.click(screen.getByRole('button', { name: 'Find candidates' }))
    expect(a.submit).toHaveBeenCalledWith({
      door: 'bom',
      spec: { text: 'holds 2 kg at 30 cm', protocol: 'CAN', part_class: 'motor' },
      load_kg: 2,
      arm_m: 0.3
    })
  })

  it('refuses an empty requirement with a message and never submits', async () => {
    const a = actions()
    render(
      <SourcingModal projectId="p1" door="bom" onClose={vi.fn()} sourcing={data({ actions: a })} />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Find candidates' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/Describe the requirement/)
    expect(a.submit).not.toHaveBeenCalled()
  })

  it('derives torque from a real assembly for the Workspace door, names unknown masses, and submits with them', async () => {
    const a = actions()
    const { rerender } = render(
      <SourcingModal
        projectId="p1"
        door="workspace"
        onClose={vi.fn()}
        sourcing={data({ actions: a })}
      />
    )
    const assembly = await screen.findByLabelText('Assembly')
    await waitFor(() => expect(within(assembly).getByText('Arm assembly')).toBeInTheDocument())
    expect(within(assembly).queryByText('Arm link')).toBeNull()
    await userEvent.selectOptions(assembly, 'asm-1')
    await userEvent.click(screen.getByRole('button', { name: 'Derive torque from geometry' }))
    expect(a.derive).toHaveBeenCalledWith({ assembly_entity_id: 'asm-1', masses: {} })
    rerender(
      <SourcingModal
        projectId="p1"
        door="workspace"
        onClose={vi.fn()}
        sourcing={data({ actions: a, torque: torque() })}
      />
    )
    await userEvent.selectOptions(screen.getByLabelText('Assembly'), 'asm-1')
    expect(screen.getByTestId('torque-card')).toHaveTextContent(
      'Required 8.24 N·m (static 5.49 N·m × 1.5 safety) from Arm assembly · not included: Camera'
    )
    await userEvent.type(screen.getByLabelText('Mass of Camera (kg)'), '0.1')
    await userEvent.click(screen.getByRole('button', { name: 'Find candidates' }))
    expect(a.submit).toHaveBeenCalledWith({
      door: 'workspace',
      spec: { text: '', part_class: 'motor' },
      assembly_entity_id: 'asm-1',
      masses: { 'p-cam': 0.1 }
    })
  })

  it('edits and saves the project rules from the panel', async () => {
    const a = actions()
    render(
      <SourcingModal projectId="p1" door="bom" onClose={vi.fn()} sourcing={data({ actions: a })} />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Edit rules' }))
    const editor = screen.getByTestId('sourcing-rules-editor')
    expect(within(editor).getByLabelText('Excluded suppliers')).toHaveValue(
      'Acme Motors: Export-controlled vendor'
    )
    await userEvent.clear(within(editor).getByLabelText('Max voltage (V)'))
    await userEvent.type(within(editor).getByLabelText('Max voltage (V)'), '36')
    await userEvent.type(within(editor).getByLabelText('Allowed protocols'), 'CAN, step/dir')
    await userEvent.click(within(editor).getByRole('button', { name: 'Save rules' }))
    expect(a.saveRules).toHaveBeenCalledWith({
      excluded_suppliers: [{ name: 'Acme Motors', reason: 'Export-controlled vendor' }],
      required_certifications: ['RoHS'],
      max_voltage_v: 36,
      allowed_protocols: ['CAN', 'step/dir'],
      preferred_suppliers: []
    })
  })
})

describe('SourcingModal — candidates and selection', () => {
  it('shows searching honestly', () => {
    render(
      <SourcingModal
        projectId="p1"
        door="bom"
        onClose={vi.fn()}
        sourcing={data({ phase: 'searching', torque: torque() })}
      />
    )
    expect(screen.getByTestId('sourcing-searching')).toHaveTextContent(
      'finding candidates for required 8.24 N·m (static 5.49 N·m × 1.5 safety)'
    )
  })

  it('compares candidates side by side, labels grounding, shows exclusions with the rule text, and selects into a category', async () => {
    const a = actions()
    render(
      <SourcingModal
        projectId="p1"
        door="workspace"
        onClose={vi.fn()}
        sourcing={data({ phase: 'candidates', request: request(), actions: a })}
      />
    )
    const table = screen.getByRole('table', { name: 'Candidate comparison' })
    expect(within(table).getByText('NEMA 23 23HS22-2804S')).toBeInTheDocument()
    expect(within(table).getByText('CITED')).toBeInTheDocument()
    expect(within(table).getByText('UNVERIFIED')).toBeInTheDocument()
    expect(
      within(table).getByText('Optimises for torque per dollar · gives up weight')
    ).toBeInTheDocument()
    expect(within(table).getByText('Voltage unknown (project maximum 24.0 V)')).toBeInTheDocument()
    const price = within(table).getByRole('row', { name: /Price/ })
    expect(price).toHaveTextContent('$24.90')
    expect(within(price).getAllByRole('cell')[1]).toHaveTextContent('—')
    const cadRow = within(table).getByRole('row', { name: /Vendor CAD/ })
    expect(
      within(cadRow).getByRole('link', { name: 'www.omc-stepperonline.com ↗' })
    ).toHaveAttribute('href', 'https://www.omc-stepperonline.com/23hs22-2804s.step')
    const excluded = screen.getByTestId('sourcing-excluded')
    expect(excluded).toHaveTextContent('Acme MegaServo 40')
    expect(excluded).toHaveTextContent(
      "Supplier 'Acme Motors' is excluded: Export-controlled vendor"
    )
    // Select the cited stepper into Actuators, quantity 2.
    const category = await screen.findByLabelText('Category for NEMA 23 23HS22-2804S')
    // Motors default to the Actuators category even when it is not listed first.
    await waitFor(() => expect(category).toHaveValue('cat-act'))
    await userEvent.clear(screen.getByLabelText('Quantity for NEMA 23 23HS22-2804S'))
    await userEvent.type(screen.getByLabelText('Quantity for NEMA 23 23HS22-2804S'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Select NEMA 23 23HS22-2804S' }))
    expect(a.select).toHaveBeenCalledWith('aaaaaaaaaaaaaaaa', {
      category_entity_id: 'cat-act',
      quantity: 2
    })
  })

  it('shows the planned part with its vendor CAD link and hands it to the door', async () => {
    const onSelected = vi.fn()
    const onClose = vi.fn()
    render(
      <SourcingModal
        projectId="p1"
        door="bom"
        onClose={onClose}
        onSelected={onSelected}
        sourcing={data({
          phase: 'selected',
          selected: entity({
            id: 'e-planned',
            name: 'NEMA 23 23HS22-2804S',
            properties: { lifecycle: 'planned', vendor_cad_url: 'https://v.example/x.step' }
          })
        })}
      />
    )
    expect(screen.getByTestId('sourcing-selected')).toHaveTextContent(
      'NEMA 23 23HS22-2804S is planned'
    )
    expect(
      screen.getByRole('link', { name: 'Get vendor CAD model from v.example ↗' })
    ).toHaveAttribute('href', 'https://v.example/x.step')
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onSelected).toHaveBeenCalledWith(expect.objectContaining({ id: 'e-planned' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows a failure and offers to try again', async () => {
    const a = actions()
    render(
      <SourcingModal
        projectId="p1"
        door="bom"
        onClose={vi.fn()}
        sourcing={data({
          phase: 'failed',
          error: 'Not enough credits to run sourcing.',
          actions: a
        })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Not enough credits')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(a.reset).toHaveBeenCalled()
  })
})
