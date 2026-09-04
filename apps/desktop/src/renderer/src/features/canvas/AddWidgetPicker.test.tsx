// SOLUSDEV-235 / EXT-15 — picker sections, duplicate gating, requirement
// hints (unknown sources = unmet), add-at-preferred-size, and the empty state.
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { AddWidgetPicker, NO_EXTENSION_WIDGETS } from './AddWidgetPicker'
import type { BuiltinWidgetEntry, ExtensionWidgetEntry } from './useAvailableWidgets'

const Noop = (): null => null
const BUILTINS: BuiltinWidgetEntry[] = [
  {
    ref: 'builtin:livebench',
    id: 'livebench',
    title: 'Live Bench',
    domains: ['simulation', 'runtime'],
    size: { preferred: 'wide', minimum: 'standard' },
    component: Noop
  },
  {
    ref: 'builtin:reference',
    id: 'reference',
    title: 'Reference',
    domains: [],
    size: { preferred: 'compact' },
    component: Noop
  }
]

function ext(overrides: Partial<ExtensionWidgetEntry> = {}): ExtensionWidgetEntry {
  return {
    ref: 'ext:bom',
    slug: 'bom',
    name: 'BOM',
    summary: 'Bill of materials',
    version: '1.2.0',
    verified: true,
    publisher: 'Solus',
    size: { preferred: 'standard' },
    requires: [],
    enabled: true,
    blocked: false,
    iconPath: null,
    hasWindow: false,
    ...overrides
  }
}

function setup(props: Partial<React.ComponentProps<typeof AddWidgetPicker>> = {}): {
  onAdd: ReturnType<typeof vi.fn>
  onClose: ReturnType<typeof vi.fn>
} {
  const onAdd = vi.fn()
  const onClose = vi.fn()
  render(
    <AddWidgetPicker
      builtins={BUILTINS}
      extensions={[ext()]}
      onCanvas={new Set(['builtin:livebench'])}
      connectedKinds={new Set()}
      onAdd={onAdd}
      onClose={onClose}
      {...props}
    />
  )
  return { onAdd, onClose }
}

const section = (name: string): ReturnType<typeof within> =>
  within(screen.getByRole('region', { name }))

describe('AddWidgetPicker', () => {
  it('lists built-ins with their domains and installed extensions with their summary', () => {
    setup()
    expect(screen.getByRole('dialog', { name: 'Add widget' })).toBeInTheDocument()
    const builtIn = section('Built-in')
    expect(builtIn.getByText('Live Bench')).toBeInTheDocument()
    expect(builtIn.getByText('simulation · runtime')).toBeInTheDocument()
    expect(builtIn.getByText('All domains')).toBeInTheDocument()
    const installed = section('Installed extensions')
    expect(installed.getByText('BOM')).toBeInTheDocument()
    expect(installed.getByText('Bill of materials')).toBeInTheDocument()
    expect(installed.getByRole('img', { name: 'Verified publisher' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /developer/i })).toBeNull()
  })

  it('marks a widget already on the canvas as Added with no Add button', () => {
    setup()
    const builtIn = section('Built-in')
    expect(builtIn.queryByRole('button', { name: 'Add Live Bench' })).toBeNull()
    expect(builtIn.getByText('Added')).toBeInTheDocument()
    expect(builtIn.getByRole('button', { name: 'Add Reference' })).toBeInTheDocument()
  })

  it('adds at the widget’s preferred size and closes', () => {
    const { onAdd, onClose } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Add Reference' }))
    expect(onAdd).toHaveBeenCalledWith('builtin:reference', 'compact')
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Add BOM' }))
    expect(onAdd).toHaveBeenLastCalledWith('ext:bom', 'standard')
  })
})

describe('AddWidgetPicker — extension requirement and policy hints', () => {
  it.each([
    ['unknown sources', undefined, 'NEEDS RUNTIME'],
    ['sources without the kind', new Set(['code'] as const), 'NEEDS RUNTIME']
  ])('shows an unmet requirement (%s) and disables Add', (_label, connected, text) => {
    setup({
      extensions: [ext({ requires: [['runtime']] })],
      connectedKinds: connected
    })
    const installed = section('Installed extensions')
    expect(installed.getByText(text)).toBeInTheDocument()
    expect(installed.queryByRole('button', { name: 'Add BOM' })).toBeNull()
  })

  it('offers Add when every requirement group is met', () => {
    setup({
      extensions: [ext({ requires: [['runtime', 'cad']] })],
      connectedKinds: new Set(['cad'])
    })
    expect(screen.getByRole('button', { name: 'Add BOM' })).toBeInTheDocument()
  })

  it.each([
    ['disabled', { enabled: false }, 'disabled in this project'],
    ['blocked', { blocked: true }, 'blocked by your team']
  ])('a %s extension shows why and cannot be added', (_label, overrides, text) => {
    setup({ extensions: [ext(overrides)] })
    const installed = section('Installed extensions')
    expect(installed.getByText(text)).toBeInTheDocument()
    expect(installed.queryByRole('button', { name: 'Add BOM' })).toBeNull()
  })
})

describe('AddWidgetPicker — empty, developer, and dismissal', () => {
  it('an empty extension section points at the Store', () => {
    const onOpenStore = vi.fn()
    setup({ extensions: [], onOpenStore })
    expect(screen.getByText(NO_EXTENSION_WIDGETS)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Browse the Store' }))
    expect(onOpenStore).toHaveBeenCalledTimes(1)
  })

  it('shows the Developer section only when dev entries are passed', () => {
    const { onAdd } = setup({
      dev: [
        {
          ref: 'ext:bom-dev',
          name: 'BOM',
          path: '~/code/solus-ext-bom',
          size: { preferred: 'full' }
        }
      ]
    })
    const dev = section('Developer (this session)')
    expect(dev.getByText('~/code/solus-ext-bom')).toBeInTheDocument()
    fireEvent.click(dev.getByRole('button', { name: 'Add BOM' }))
    expect(onAdd).toHaveBeenCalledWith('ext:bom-dev', 'full')
  })

  it('closes on Escape and on the ✕ button without adding', () => {
    const { onAdd, onClose } = setup()
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
    expect(onAdd).not.toHaveBeenCalled()
  })
})
