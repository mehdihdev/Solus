// SOLUSDEV-235 / EXT-16 — what Live Bench adds AROUND the canvas: the header
// status line (honest about unknown vs. nothing streaming), the connected
// source kinds handed to the picker, and Store navigation. The canvas itself
// is mocked here; features/canvas carries its own tests.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Focus, SourceKind } from '@solus/shared-types'
import type { WidgetCanvasProps } from '../canvas'
import type { BenchSession, Source } from '../../lib/api/resources'
import type { ProjectSourcesData } from '../project/useProjectSources'
import { fakeManifest } from '../extensions/frame/testing/fixtures'
import { useDevExtensionsStore, type DevExtensionEntry } from '../devExtensions/devExtensionsStore'
import { BenchCanvasHost } from './BenchCanvasHost'

vi.mock('../canvas', () => ({
  WidgetCanvas: (props: WidgetCanvasProps) => (
    <div data-testid="canvas-mock" data-project={props.projectId}>
      {props.header}
      <span data-testid="kinds">
        {props.connectedKinds === null || props.connectedKinds === undefined
          ? 'unknown'
          : [...props.connectedKinds].sort().join(',')}
      </span>
      {props.onOpenStore && (
        <button type="button" onClick={props.onOpenStore}>
          open store
        </button>
      )}
      <span data-testid="dev">
        {(props.dev ?? []).map((d) => `${d.ref}|${d.name}|${d.path}|${d.size.preferred}`).join(';')}
      </span>
    </div>
  )
}))

const sourcesMock = vi.hoisted(() => vi.fn())
vi.mock('../project/useProjectSources', () => ({ useProjectSources: sourcesMock }))

const FOCUS: Focus = {
  entity: { projectId: 'p1', entityId: 'e1' },
  domain: 'mechanical',
  label: 'elbow motor',
  path: []
}

const SESSION = { id: 's1', device_ids: [] } as unknown as BenchSession

function devEntry(
  slug: string,
  views: ReturnType<typeof fakeManifest>['views'] = {
    widget: { entry: 'w.html', preferred: 'wide', minimum: 'standard' }
  }
): DevExtensionEntry {
  return {
    manifest: fakeManifest({
      extension: { ...fakeManifest().extension, id: slug, name: slug.toUpperCase() },
      views
    }),
    devPath: `/code/${slug}`,
    loadedAt: '2026-09-05T00:00:00Z',
    acknowledged: true,
    problems: []
  }
}

function sources(status: ProjectSourcesData['status'], types: string[] = []): void {
  sourcesMock.mockReturnValue({
    status,
    sources: types.map((type, i) => ({ id: `s${i}`, type }) as unknown as Source),
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
}

function mount(
  overrides: Partial<Parameters<typeof BenchCanvasHost>[0]> = {}
): ReturnType<typeof vi.fn> {
  const onNavigate = vi.fn()
  render(
    <BenchCanvasHost
      projectId="p1"
      focus={null}
      onFocusChange={vi.fn()}
      sessions={null}
      onNavigate={onNavigate}
      {...overrides}
    />
  )
  return onNavigate
}

describe('BenchCanvasHost', () => {
  it('puts the title and the focused part into the canvas header', () => {
    sources('ready')
    mount({ focus: FOCUS })
    const canvas = screen.getByTestId('canvas-mock')
    expect(canvas).toHaveAttribute('data-project', 'p1')
    expect(screen.getByRole('heading', { name: 'Live Bench' })).toBeInTheDocument()
    expect(screen.getByText('FOCUSED')).toBeInTheDocument()
    expect(screen.getByText('elbow motor')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect a device' })).toBeNull()
  })

  it('stays focused even while sessions report streaming devices', () => {
    sources('ready')
    mount({ focus: FOCUS, sessions: [SESSION] })
    expect(screen.getByText('FOCUSED')).toBeInTheDocument()
    expect(screen.queryByText('NOTHING STREAMING')).toBeNull()
  })

  it('offers Connect a device only once nothing is known to be streaming', () => {
    sources('ready')
    const onNavigate = mount({ sessions: [] })
    expect(screen.getByText('NOTHING STREAMING')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Connect a device' }))
    expect(onNavigate).toHaveBeenCalledWith('sources')
  })

  it('says only that no part is focused while sessions are unknown', () => {
    sources('ready')
    mount({ sessions: null })
    expect(screen.getByText('NO PART FOCUSED')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect a device' })).toBeNull()
  })

  it('hands the picker the connected source KINDS (github → code, kicad → eda), unknown types dropped', () => {
    sources('ready', ['github', 'kicad', 'not-a-kind'])
    mount()
    const kinds = screen.getByTestId('kinds').textContent?.split(',') as SourceKind[]
    expect(kinds).toEqual(['code', 'eda'])
  })

  it('reports kinds as unknown (every requirement unmet) when the sources list is offline', () => {
    sources('offline', ['github'])
    mount()
    expect(screen.getByTestId('kinds')).toHaveTextContent('unknown')
  })

  it('routes the picker’s Store link through shell navigation', () => {
    sources('ready')
    const onNavigate = mount()
    fireEvent.click(screen.getByRole('button', { name: 'open store' }))
    expect(onNavigate).toHaveBeenCalledWith('store')
  })
})

describe('BenchCanvasHost — developer registrations (EXT-20)', () => {
  beforeEach(() => useDevExtensionsStore.getState().reset())

  it('lists only validated registrations with a widget view, as picker rows', () => {
    sources('ready')
    useDevExtensionsStore.setState({
      entries: {
        lab: devEntry('lab'),
        'page-only': devEntry('page-only', {
          page: { entry: 'p.html', icon: 'i.svg', label: 'Page' }
        }),
        broken: {
          manifest: null,
          devPath: '/code/broken',
          loadedAt: 'x',
          acknowledged: true,
          problems: ['nope']
        }
      }
    })
    mount()
    expect(screen.getByTestId('dev')).toHaveTextContent('ext:lab|LAB|/code/lab|wide')
    expect(screen.getByTestId('dev').textContent?.split(';')).toHaveLength(1)
  })

  it('hands the canvas the session’s dev widgets and drops them when the registration goes', () => {
    sources('ready')
    useDevExtensionsStore.setState({ entries: { lab: devEntry('lab') } })
    mount()
    expect(screen.getByTestId('dev')).toHaveTextContent('ext:lab|LAB|/code/lab|wide')
    act(() => useDevExtensionsStore.setState({ entries: {} }))
    expect(screen.getByTestId('dev')).toHaveTextContent('')
  })
})
