// SOLUSDEV-317: the command card header (program + risk badges + sandboxed) and
// the Approve shortcut hint. Presentation only — the verbatim rows are unchanged.
import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { ConfirmationCard } from './ConfirmationCard'
import { CommandApprovalContext, createApprovalRegistry } from './commandHotkey'
import { PreviewObserverContext, type ObserveInView } from './previewInView'

const EXEC: PendingConfirmation = {
  confirmationId: 'cx',
  tool: 'code.exec',
  summary: 'Run colcon build',
  preview: [
    { label: 'program', before: null, after: '/opt/ros/jazzy/bin/colcon<img src=x>' },
    { label: 'command', before: null, after: '["colcon","build"]' },
    {
      label: 'sandbox',
      before: null,
      after: 'sandbox-exec — writes limited to the workspace, temp and tool caches'
    },
    { label: 'risk', before: null, after: 'network, project_scripts' }
  ]
}

const ONSHAPE: PendingConfirmation = {
  confirmationId: 'co',
  tool: 'onshape.set_variable',
  summary: 'Set width',
  preview: [{ label: 'width', before: '1', after: '2' }]
}

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('command card header', () => {
  it('shows the program basename, one badge per risk and a sandboxed badge', () => {
    const view = render(<ConfirmationCard pending={EXEC} onDecide={vi.fn()} />)
    const header = screen.getByLabelText('Command')
    expect(within(header).getByText('colcon<img src=x>')).toBeInTheDocument()
    expect(view.container.querySelector('img')).toBeNull()
    expect(within(header).getByText('network')).toBeInTheDocument()
    expect(within(header).getByText('project_scripts')).toBeInTheDocument()
    expect(within(header).getByText('sandboxed')).toBeInTheDocument()
  })

  it('keeps every verbatim row in the preview', () => {
    render(<ConfirmationCard pending={EXEC} onDecide={vi.fn()} />)
    const rows = screen.getByRole('list', { name: 'Proposed changes' })
    for (const label of ['program', 'command', 'sandbox', 'risk']) {
      expect(within(rows).getByText(label)).toBeInTheDocument()
    }
  })

  it('has no command header or shortcut hint on a non-command card', () => {
    render(<ConfirmationCard pending={ONSHAPE} onDecide={vi.fn()} />)
    expect(screen.queryByLabelText('Command')).toBeNull()
    expect(screen.queryByText('Ctrl↵')).toBeNull()
    expect(screen.getByRole('button', { name: 'Approve' })).not.toHaveAttribute('aria-keyshortcuts')
  })
})

describe('approve shortcut hint', () => {
  it('shows Ctrl↵ off macOS without changing the button name', () => {
    render(<ConfirmationCard pending={EXEC} onDecide={vi.fn()} />)
    const approve = screen.getByRole('button', { name: 'Approve' })
    expect(within(approve).getByText('Ctrl↵')).toBeInTheDocument()
    expect(approve).toHaveAttribute('aria-keyshortcuts', 'Control+Enter')
  })

  it('shows ⌘↵ on macOS', () => {
    ;(window as unknown as { solus: { platform: string } }).solus = { platform: 'darwin' }
    render(<ConfirmationCard pending={EXEC} onDecide={vi.fn()} />)
    const approve = screen.getByRole('button', { name: 'Approve' })
    expect(within(approve).getByText('⌘↵')).toBeInTheDocument()
    expect(approve).toHaveAttribute('aria-keyshortcuts', 'Meta+Enter')
  })
})

describe('command preview is open', () => {
  it('renders the verbatim preview of a command card expanded and bounded', () => {
    render(<ConfirmationCard pending={EXEC} onDecide={vi.fn()} />)
    const region = screen.getByRole('region', { name: 'Complete proposed changes' })
    expect(region.closest('details')).toHaveAttribute('open')
    expect(region).toHaveClass('confirmation-card__scroll')
  })

  it('keeps a long non-command preview collapsed', () => {
    const many = {
      ...ONSHAPE,
      preview: [1, 2, 3].map((n) => ({ ...ONSHAPE.preview[0], label: `v${n}` }))
    }
    render(<ConfirmationCard pending={many} onDecide={vi.fn()} />)
    const region = screen.getByRole('region', { name: 'Complete proposed changes', hidden: true })
    expect(region.closest('details')).not.toHaveAttribute('open')
  })

  it('reports the preview region in view to the arming clock, and forgets it on unmount', () => {
    let now = 1000
    const registry = createApprovalRegistry(() => now)
    let report: ((visible: boolean) => void) | null = null
    const observed: Element[] = []
    const stop = vi.fn()
    const observe: ObserveInView = (element, onChange) => {
      observed.push(element)
      report = onChange
      return stop
    }
    const view = render(
      <CommandApprovalContext.Provider value={registry}>
        <PreviewObserverContext.Provider value={observe}>
          <ConfirmationCard pending={EXEC} onDecide={vi.fn()} />
        </PreviewObserverContext.Provider>
      </CommandApprovalContext.Provider>
    )
    expect(observed).toEqual([screen.getByRole('region', { name: 'Complete proposed changes' })])
    expect(registry.inViewSince('cx')).toBeNull()
    now = 2000
    report!(true)
    expect(registry.inViewSince('cx')).toBe(2000)
    view.unmount()
    expect(stop).toHaveBeenCalled()
    expect(registry.inViewSince('cx')).toBeNull()
  })

  it('does not observe a non-command card', () => {
    const observe = vi.fn(() => () => undefined)
    render(
      <CommandApprovalContext.Provider value={createApprovalRegistry()}>
        <PreviewObserverContext.Provider value={observe}>
          <ConfirmationCard pending={ONSHAPE} onDecide={vi.fn()} />
        </PreviewObserverContext.Provider>
      </CommandApprovalContext.Provider>
    )
    expect(observe).not.toHaveBeenCalled()
  })

  it('keeps one keyboard registration across re-renders with a fresh onDecide', () => {
    const registry = createApprovalRegistry()
    const register = vi.spyOn(registry, 'register')
    const wrap = (onDecide: () => Promise<void>): React.JSX.Element => (
      <CommandApprovalContext.Provider value={registry}>
        <ConfirmationCard pending={EXEC} onDecide={onDecide} />
      </CommandApprovalContext.Provider>
    )
    const view = render(wrap(vi.fn()))
    view.rerender(wrap(vi.fn()))
    view.rerender(wrap(vi.fn()))
    expect(register).toHaveBeenCalledTimes(1)
  })
})
