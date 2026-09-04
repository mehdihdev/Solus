// SOLUSDEV-235 / EXT-15 — the canvas end to end with an injected client:
// skeleton → default slot, chrome (size menu gated by minimum, move, remove,
// state dot), extension slots through a mocked ExtensionFrame, the empty
// state, the save/offline/pruned notes, and the picker adding at preferred size.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { useEffect } from 'react'
import type { Focus, WidgetManifest, WidgetProps } from '@solus/shared-types'
import type { WidgetLayoutApi, WidgetLayoutSlotApi } from '../../lib/api/resources.extensions'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import { OFFLINE_NOTE, prunedNote } from './canvasCopy'
import { TOO_SMALL } from './SlotMenu'
import type { AvailableWidgetsDeps } from './useAvailableWidgets'
import { SAVE_DEBOUNCE_MS, type WidgetLayoutDeps } from './useWidgetLayout'
import { WidgetCanvas } from './WidgetCanvas'

vi.mock('../extensions/frame/ExtensionFrame', () => ({
  ExtensionFrame: (props: { slug: string; view: string }) => (
    <div data-testid="extension-frame-mock" data-slug={props.slug} data-view={props.view} />
  )
}))

function FakeBench({ focus, onFocusChange, onStateChange }: WidgetProps): React.JSX.Element {
  useEffect(() => {
    onStateChange?.(focus === null ? 'empty' : 'ready')
  }, [focus, onStateChange])
  return (
    <div data-testid="fake-bench">
      {focus?.label ?? 'no focus'}
      <button type="button" onClick={() => onFocusChange(null)}>
        clear focus
      </button>
    </div>
  )
}

function FailingWidget({ onStateChange }: WidgetProps): React.JSX.Element {
  useEffect(() => {
    onStateChange?.('error')
  }, [onStateChange])
  return <p>broken</p>
}

const MANIFESTS: WidgetManifest[] = [
  {
    id: 'livebench',
    title: 'Live Bench',
    domains: ['runtime'],
    size: { preferred: 'wide', minimum: 'standard' },
    component: FakeBench
  },
  {
    id: 'broken',
    title: 'Broken',
    domains: [],
    size: { preferred: 'compact' },
    component: FailingWidget
  },
  {
    id: 'reference',
    title: 'Reference',
    domains: [],
    size: { preferred: 'compact' },
    component: () => <p>reference body</p>
  }
]

const bomInstall = fakeInstall({
  version: {
    ...fakeInstall().version,
    manifest: fakeManifest({ views: { widget: { entry: 'widget.html', preferred: 'standard' } } })
  }
})

const FOCUS: Focus = {
  entity: { projectId: 'p1', entityId: 'e1' },
  domain: 'runtime',
  label: 'motor',
  path: []
}

function api(layout: WidgetLayoutSlotApi[], updatedAt: string | null = 'x'): WidgetLayoutApi {
  return { project_id: 'p1', layout, updated_at: updatedAt }
}

interface Harness {
  layoutDeps: WidgetLayoutDeps & { save: ReturnType<typeof vi.fn> }
  widgetsDeps: AvailableWidgetsDeps
  onFocusChange: ReturnType<typeof vi.fn>
}

function harness(
  stored: WidgetLayoutSlotApi[] | null,
  overrides: Partial<WidgetLayoutDeps> = {}
): Harness {
  return {
    layoutDeps: {
      load: vi.fn(async () => (stored === null ? api([], null) : api(stored))),
      save: vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) => api([...layout])),
      ...overrides
    } as Harness['layoutDeps'],
    widgetsDeps: { discover: () => MANIFESTS, listInstalls: vi.fn(async () => [bomInstall]) },
    onFocusChange: vi.fn()
  }
}

function mount(h: Harness, focus: Focus | null = FOCUS): void {
  render(
    <WidgetCanvas
      projectId="p1"
      focus={focus}
      onFocusChange={h.onFocusChange}
      header={<h1>Live Bench</h1>}
      layoutDeps={h.layoutDeps}
      widgetsDeps={h.widgetsDeps}
    />
  )
}

const flush = (): Promise<void> => act(async () => {})
const tick = (ms: number): Promise<void> =>
  act(async () => {
    vi.advanceTimersByTime(ms)
  })
const slots = (): HTMLElement[] => screen.queryAllByTestId('widget-slot')
const openMenu = (title: string): HTMLElement => {
  fireEvent.click(screen.getByRole('button', { name: `${title} slot options` }))
  return screen.getByRole('menu', { name: `${title} slot options` })
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('WidgetCanvas — loading and the default slot', () => {
  it('shows a skeleton (no Add affordance) until the layout loads, then the default Live Bench slot', async () => {
    const h = harness(null)
    mount(h)
    expect(screen.getByTestId('canvas-skeleton')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add widget/i })).toBeNull()
    expect(screen.getByText('Live Bench', { selector: 'h1' })).toBeInTheDocument()
    await flush()
    expect(screen.queryByTestId('canvas-skeleton')).toBeNull()
    const [slot] = slots()
    expect(slots()).toHaveLength(1)
    expect(slot).toHaveAttribute('data-ref', 'builtin:livebench')
    expect(slot).toHaveAttribute('data-span', '3')
    expect(slot).toHaveClass('screen-in')
    expect(within(slot).getByText('wide')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add widget/i })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
    expect(h.layoutDeps.save).not.toHaveBeenCalled()
  })

  it('hands built-ins the focus and routes their focus changes back through the canvas', async () => {
    const h = harness(null)
    mount(h)
    await flush()
    expect(screen.getByTestId('fake-bench')).toHaveTextContent('motor')
    fireEvent.click(screen.getByRole('button', { name: 'clear focus' }))
    expect(h.onFocusChange).toHaveBeenCalledWith(null)
  })
})

describe('WidgetCanvas — slot chrome', () => {
  it('the size menu disables sizes below the widget’s minimum and resizes on pick', async () => {
    const h = harness(null)
    mount(h)
    await flush()
    const menu = openMenu('Live Bench')
    const compact = within(menu).getByRole('menuitemradio', { name: 'Compact' })
    expect(compact).toBeDisabled()
    expect(compact).toHaveAttribute('title', TOO_SMALL)
    expect(within(menu).getByRole('menuitemradio', { name: 'Standard' })).toBeEnabled()
    expect(within(menu).getByRole('menuitemradio', { name: /Wide/ })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'Full' }))
    expect(screen.queryByRole('menu')).toBeNull()
    expect(slots()[0]).toHaveAttribute('data-span', '4')
    expect(screen.getByRole('status')).toHaveTextContent('Saving…')
    await tick(SAVE_DEBOUNCE_MS)
    await flush()
    expect(h.layoutDeps.save).toHaveBeenCalledWith('p1', [
      { ref: 'builtin:livebench', size: 'full' }
    ])
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
  })

  it('moves slots left/right with the ends disabled', async () => {
    const h = harness([
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'builtin:reference', size: 'compact' }
    ])
    mount(h)
    await flush()
    let menu = openMenu('Live Bench')
    expect(within(menu).getByRole('menuitem', { name: 'Move left' })).toBeDisabled()
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Move right' }))
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:reference', 'builtin:livebench'])
    menu = openMenu('Live Bench')
    expect(within(menu).getByRole('menuitem', { name: 'Move right' })).toBeDisabled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('removes a slot immediately; removing the last one yields the empty state, Restore default brings Live Bench back', async () => {
    const h = harness(null)
    mount(h)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Live Bench' }))
    expect(slots()).toHaveLength(0)
    expect(screen.getByText('Nothing on your bench.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Restore default' }))
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench'])
    await tick(SAVE_DEBOUNCE_MS)
    expect(h.layoutDeps.save).toHaveBeenCalledTimes(1)
  })
})

describe('WidgetCanvas — slot bodies', () => {
  it('shows a warn dot when a built-in reports error, and nothing when ready', async () => {
    const h = harness([
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'builtin:broken', size: 'compact' }
    ])
    mount(h)
    await flush()
    const [bench, broken] = slots()
    expect(within(bench).queryByTestId('slot-state')).toBeNull()
    expect(within(broken).getByTestId('slot-state')).toHaveAttribute('data-state', 'error')
    expect(within(broken).getByRole('img', { name: 'Widget error' })).toBeInTheDocument()
  })

  it('renders an extension slot through ExtensionFrame in widget mode, titled by the install', async () => {
    const h = harness([{ ref: 'ext:bom', size: 'standard' }])
    mount(h)
    await flush()
    const [slot] = slots()
    expect(slot).toHaveAttribute('aria-label', 'BOM')
    expect(slot).toHaveAttribute('data-span', '2')
    const frame = within(slot).getByTestId('extension-frame-mock')
    expect(frame).toHaveAttribute('data-slug', 'bom')
    expect(frame).toHaveAttribute('data-view', 'widget')
  })
})

describe('WidgetCanvas — honesty notes', () => {
  it('a failed PUT shows the offline note with Retry, and Retry re-sends', async () => {
    let fail = true
    const h = harness(null, {
      save: vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) => {
        if (fail) throw new TypeError('network')
        return api([...layout])
      })
    })
    mount(h)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Live Bench' }))
    await tick(SAVE_DEBOUNCE_MS)
    await flush()
    expect(screen.getByRole('status')).toHaveTextContent(OFFLINE_NOTE)
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await flush()
    expect(h.layoutDeps.save).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
  })

  it('a failed GET renders the default offline, still editable', async () => {
    const h = harness(null, {
      load: vi.fn(async () => {
        throw new TypeError('network')
      })
    })
    mount(h)
    await flush()
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench'])
    expect(screen.getByRole('status')).toHaveTextContent(OFFLINE_NOTE)
  })

  it('prunes refs this build or install snapshot cannot render and says how many', async () => {
    const h = harness([
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'builtin:gone', size: 'compact' },
      { ref: 'ext:uninstalled', size: 'standard' }
    ])
    mount(h)
    await flush()
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench'])
    expect(screen.getByText(prunedNote(2))).toBeInTheDocument()
    expect(prunedNote(1)).toBe("1 widget from your saved layout isn't available and was removed.")
  })
})

describe('WidgetCanvas — picker', () => {
  it('opens from the header, adds at the preferred size, and closes', async () => {
    const h = harness(null)
    mount(h)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: /add widget/i }))
    const dialog = screen.getByRole('dialog', { name: 'Add widget' })
    expect(within(dialog).getByText('Added')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add BOM' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    const added = slots()[1]
    expect(added).toHaveAttribute('data-ref', 'ext:bom')
    expect(added).toHaveAttribute('data-span', '2')
    await tick(SAVE_DEBOUNCE_MS)
    expect(h.layoutDeps.save).toHaveBeenCalledWith('p1', [
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'ext:bom', size: 'standard' }
    ])
  })

  it('opens from the empty state too', async () => {
    const h = harness([])
    mount(h)
    await flush()
    expect(screen.getByText('Nothing on your bench.')).toBeInTheDocument()
    // The header button and the empty state's call to action both open it.
    const buttons = screen.getAllByRole('button', { name: /add widget/i })
    expect(buttons).toHaveLength(2)
    fireEvent.click(buttons[1])
    fireEvent.click(screen.getByRole('button', { name: 'Add Reference' }))
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:reference'])
    expect(screen.getByText('reference body')).toBeInTheDocument()
  })
})
