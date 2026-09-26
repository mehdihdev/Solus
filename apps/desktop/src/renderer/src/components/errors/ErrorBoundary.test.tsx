// SOLUSDEV-311 acceptance, as tests: a component that throws renders the
// fallback; its siblings keep rendering; Reload panel recovers once the fault
// is gone; the reporter is called once per error.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorBoundary } from './ErrorBoundary'
import { useSettingsStore } from '../../store/settingsStore'

let shouldThrow = true
function Flaky(): React.JSX.Element {
  if (shouldThrow) throw new TypeError('bench exploded')
  return <p>bench is fine</p>
}

// React logs caught render errors to console.error; keep test output readable.
let quiet: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  shouldThrow = true
  useSettingsStore.setState({ solMode: 'Guide' })
  quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined)
})
afterEach(() => quiet.mockRestore())

function Shell({ report }: { report: ReturnType<typeof vi.fn> }): React.JSX.Element {
  return (
    <div>
      <nav>rail</nav>
      <ErrorBoundary surface="bench" scope="panel" reporter={{ report }}>
        <Flaky />
      </ErrorBoundary>
      <ErrorBoundary surface="workspace" scope="panel" reporter={{ report }}>
        <p>workspace panel</p>
      </ErrorBoundary>
    </div>
  )
}

describe('ErrorBoundary', () => {
  it('renders the fallback in place of a component that throws', () => {
    render(<Shell report={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Live Bench hit a problem')
    expect(screen.queryByText('bench is fine')).toBeNull()
  })

  it('keeps siblings and the nav rendering', () => {
    render(<Shell report={vi.fn()} />)
    expect(screen.getByText('rail')).toBeInTheDocument()
    expect(screen.getByText('workspace panel')).toBeInTheDocument()
  })

  it('Reload panel recovers once the fault is gone', () => {
    render(<Shell report={vi.fn()} />)
    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: 'Reload panel' }))
    expect(screen.getByText('bench is fine')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('calls the reporter exactly once per error, with the component stack', () => {
    const report = vi.fn()
    render(<Shell report={report} />)
    expect(report).toHaveBeenCalledTimes(1)
    const [error, context] = report.mock.calls[0]
    expect(error).toBeInstanceOf(TypeError)
    expect(context).toMatchObject({ origin: 'render', surface: 'bench' })
    expect(context.componentStack).toContain('Flaky')
  })

  it('reports again if the panel throws again after a reload', () => {
    const report = vi.fn()
    render(<Shell report={report} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reload panel' }))
    expect(report).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('offers Reload app and Copy details', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<Shell report={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Reload app' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy details' }))
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('Error: TypeError: bench exploded')
    )
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('uses Expert wording when the SOL mode is Expert', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<Shell report={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Live Bench crashed')
    expect(screen.getByRole('alert')).toHaveTextContent('TypeError: bench exploded')
  })

  it('app scope has no Reload panel', () => {
    render(
      <ErrorBoundary surface="root" scope="app" reporter={{ report: vi.fn() }}>
        <Flaky />
      </ErrorBoundary>
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Solus hit a problem')
    expect(screen.queryByRole('button', { name: 'Reload panel' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Reload app' })).toBeInTheDocument()
  })

  it('silent scope (the click-through overlay) reports but draws nothing', () => {
    const report = vi.fn()
    const { container } = render(
      <ErrorBoundary surface="overlay" scope="silent" reporter={{ report }}>
        <Flaky />
      </ErrorBoundary>
    )
    expect(container).toBeEmptyDOMElement()
    expect(report).toHaveBeenCalledTimes(1)
  })
})
