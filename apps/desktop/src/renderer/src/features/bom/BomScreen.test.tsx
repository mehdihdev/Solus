// SOLUSDEV-246 / STORE ST4 — the BOM page: one row per physical part, lifecycle
// state per row, planned purchases and raw materials, config from the bundle's
// settings, CSV export, and the honest states.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as hook from './useBom'
import { BomScreen } from './BomScreen'
import { bomView, designRow, purchaseRow } from './testing/fixtures'

vi.mock('./useBom', async (importOriginal) => ({
  ...(await importOriginal<typeof hook>()),
  useBom: vi.fn()
}))

function actions(over: Partial<hook.BomActions> = {}): hook.BomActions {
  return {
    addRow: vi.fn(async () => ({ ok: true }) as hook.BomOutcome),
    patchRow: vi.fn(async () => ({ ok: true }) as hook.BomOutcome),
    setState: vi.fn(async () => ({ ok: true }) as hook.BomOutcome),
    removeRow: vi.fn(async () => ({ ok: true }) as hook.BomOutcome),
    exportCsv: vi.fn(async () => ({ ok: true }) as hook.BomOutcome),
    refresh: vi.fn(async () => undefined),
    ...over
  }
}

function mockBom(data: Partial<hook.BomData>): hook.BomActions {
  const a = data.actions ?? actions()
  vi.mocked(hook.useBom).mockReturnValue({
    status: 'ready',
    view: bomView(),
    ...data,
    actions: a
  })
  return a
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' } })
})

const PUBLISHER = { displayName: 'Solus', verified: true }

function renderScreen(props: Partial<Parameters<typeof BomScreen>[0]> = {}): void {
  render(
    <BomScreen
      projectId="p1"
      slug="bom"
      publisher={PUBLISHER}
      onBack={vi.fn()}
      onOpenStore={vi.fn()}
      {...props}
    />
  )
}

describe('BomScreen', () => {
  it('lists one row per physical part with its sources, kind, quantity and state', () => {
    mockBom({})
    renderScreen()
    expect(screen.getByRole('heading', { level: 1, name: 'BOM' })).toBeInTheDocument()
    expect(screen.getByTestId('ext-page-header')).toHaveTextContent('by Solus')
    const servo = screen.getByRole('row', { name: /MG996R/ })
    expect(within(servo).getByText('TowerPro')).toBeInTheDocument()
    expect(within(servo).getByText('electrical: U3 · mechanical: Servo body')).toBeInTheDocument()
    expect(within(servo).getByText('DESIGN')).toBeInTheDocument()
    expect(within(servo).getByRole('combobox', { name: /Lifecycle state/ })).toHaveValue(
      'installed'
    )
    const motor = screen.getByRole('row', { name: /NEMA 17 stepper/ })
    expect(within(motor).getByText('PURCHASE')).toBeInTheDocument()
    expect(within(motor).getByRole('combobox', { name: /Lifecycle state/ })).toHaveValue('planned')
    expect(screen.getByText(/2 rows · 1 priced · total/)).toBeInTheDocument()
  })

  it('changes a row’s lifecycle state through the actions', async () => {
    const a = mockBom({})
    renderScreen()
    const motor = screen.getByRole('row', { name: /NEMA 17 stepper/ })
    await userEvent.selectOptions(
      within(motor).getByRole('combobox', { name: /Lifecycle state/ }),
      'ordered'
    )
    expect(a.setState).toHaveBeenCalledWith(purchaseRow().key, 'ordered')
  })

  it('adds a planned purchase and a raw material through the dialog', async () => {
    const a = mockBom({})
    renderScreen()
    await userEvent.click(screen.getByRole('button', { name: 'Add row' }))
    const dialog = screen.getByRole('dialog', { name: 'Add a BOM row' })
    await userEvent.type(within(dialog).getByLabelText('Name'), '6061-T6 plate 3 mm')
    await userEvent.selectOptions(within(dialog).getByLabelText('Category'), 'raw_material')
    await userEvent.clear(within(dialog).getByLabelText('Quantity'))
    await userEvent.type(within(dialog).getByLabelText('Quantity'), '4')
    await userEvent.type(within(dialog).getByLabelText('Unit cost'), '3.5')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add to BOM' }))
    await waitFor(() =>
      expect(a.addRow).toHaveBeenCalledWith({
        name: '6061-T6 plate 3 mm',
        category: 'raw_material',
        quantity: 4,
        unit_cost: 3.5
      })
    )
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('keeps the dialog open and explains when the add is refused', async () => {
    mockBom({
      actions: actions({
        addRow: vi.fn(async () => ({ ok: false, message: 'Only project members can add rows.' }))
      })
    })
    renderScreen()
    await userEvent.click(screen.getByRole('button', { name: 'Add row' }))
    const dialog = screen.getByRole('dialog', { name: 'Add a BOM row' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Motor')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add to BOM' }))
    expect(await within(dialog).findByText(/Only project members/)).toBeInTheDocument()
  })

  it('removes an item row after a confirm, and never offers removal on a design row', async () => {
    const a = mockBom({})
    renderScreen()
    const servo = screen.getByRole('row', { name: /MG996R/ })
    expect(within(servo).queryByRole('button', { name: /Remove/ })).toBeNull()
    const motor = screen.getByRole('row', { name: /NEMA 17 stepper/ })
    await userEvent.click(within(motor).getByRole('button', { name: 'Remove NEMA 17 stepper' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove row' }))
    expect(a.removeRow).toHaveBeenCalledWith(purchaseRow().key)
  })

  it('exports a CSV named after the project', async () => {
    const a = mockBom({})
    renderScreen()
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    expect(a.exportCsv).toHaveBeenCalledWith('bom-rover-mk3.csv')
  })

  it('shows the configured suppliers, currency and cost target', () => {
    mockBom({
      view: bomView({
        config: { preferred_suppliers: ['Mouser', 'Digi-Key'], cost_target: 250, currency: 'EUR' },
        totals: {
          rows: 2,
          priced_rows: 1,
          line_cost_total: 29,
          cost_target: 250,
          over_target: false
        }
      })
    })
    renderScreen()
    expect(screen.getByText(/Preferred suppliers: Mouser, Digi-Key/)).toBeInTheDocument()
    expect(screen.getByText(/within target/)).toBeInTheDocument()
  })

  it('is honest when empty, not installed, or offline', () => {
    mockBom({ view: bomView({ rows: [] }) })
    const { unmount } = render(<BomScreen projectId="p1" slug="bom" publisher={PUBLISHER} />)
    expect(screen.getByText(/No parts yet/)).toBeInTheDocument()
    unmount()

    const onOpenStore = vi.fn()
    mockBom({ status: 'not_installed', view: null })
    const second = render(
      <BomScreen projectId="p1" slug="bom" publisher={PUBLISHER} onOpenStore={onOpenStore} />
    )
    expect(screen.getByText(/isn't installed in this project/)).toBeInTheDocument()
    screen.getByRole('button', { name: 'Open in Store' }).click()
    expect(onOpenStore).toHaveBeenCalledOnce()
    second.unmount()

    mockBom({ status: 'offline', view: null })
    render(<BomScreen projectId="p1" slug="bom" publisher={null} />)
    expect(screen.getByText(/can't reach Solus/)).toBeInTheDocument()
  })

  it('notes a truncated view rather than pretending it is complete', () => {
    mockBom({ view: bomView({ truncated: true }) })
    renderScreen()
    expect(screen.getByText(/bounded subset/)).toBeInTheDocument()
    expect(screen.getByText(designRow().name)).toBeInTheDocument()
  })
})
