// SOLUSDEV-326 P3: the Hardware page's parts list (docs/wireflows/hardware-onboarding.md).
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { ExpectedParts } from '../../lib/api/hardware'
import { useDeviceStore } from './deviceStore'
import { PartsList } from './PartsList'
import css from './partsList.css?raw'
import { device } from './testing/fixtures'
import { machine, part, robot } from './testing/parts'

const api = vi.hoisted(() => ({
  listEntities: vi.fn(),
  listHardwareParts: vi.fn(),
  listExpectedParts: vi.fn(),
  setInGraph: vi.fn()
}))
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  listEntities: api.listEntities
}))
vi.mock('../../lib/api/hardware', async (original) => ({
  ...(await original<typeof import('../../lib/api/hardware')>()),
  listHardwareParts: api.listHardwareParts,
  listExpectedParts: api.listExpectedParts,
  setInGraph: api.setInGraph
}))

const NOTHING: ExpectedParts = { expected: [], sources: [], more: 0 }
const EXPECTED: ExpectedParts = {
  expected: [
    { name: 'wrist_cam', what: 'sensor_msgs/Image', robot_id: null, source: 'arm.yaml' },
    { name: 'gripper', what: 'STS3215', robot_id: 'r1', source: 'Rover arm' }
  ],
  sources: ['arm.yaml', 'Rover arm'],
  more: 1
}

interface World {
  robots?: ReturnType<typeof robot>[]
  parts?: ReturnType<typeof part>[]
  expected?: ExpectedParts
}

function serve({ robots = [], parts = [], expected = NOTHING }: World): void {
  api.listEntities.mockImplementation((_project: string, filters: { type?: string }) =>
    Promise.resolve(filters.type === 'physical_robot' ? robots : [])
  )
  api.listHardwareParts.mockResolvedValue(parts)
  api.listExpectedParts.mockResolvedValue(expected)
}

const ARM = {
  robots: [robot('r1', 'Rover arm', { in_graph: false })],
  parts: [
    part('p1', 'shoulder_pan', { parent_id: 'r1', model: 'STS3215', in_graph: false }),
    part('p2', 'motor_driver', { in_graph: false })
  ]
}

async function shown(world: World): Promise<void> {
  serve(world)
  render(<PartsList projectId="proj" />)
  await screen.findByRole('heading', { level: 2, name: /Robot parts/ })
  await waitFor(() => expect(api.listExpectedParts).toHaveBeenCalled())
  await act(async () => {})
}

const rowOf = (name: string): HTMLElement => screen.getByText(name).closest('[role="row"]')!
const groupRow = (name: string): HTMLElement =>
  screen
    .getAllByRole('row')
    .find((row) => row.matches('.hw-group') && row.textContent?.startsWith(name))!

beforeEach(() => {
  vi.clearAllMocks()
  useDeviceStore.getState().reset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('PartsList', () => {
  it('draws the heading with the count, the column headers and the groups', async () => {
    await shown(ARM)
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Robot parts · 2')
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Part',
      'What it is',
      'Robot',
      'In workspace graph',
      'Status'
    ])
    expect(groupRow('Rover arm')).toHaveTextContent('Rover arm · 1 part')
    expect(rowOf('Not on a robot')).toHaveTextContent('Not on a robot · 1')
    expect(rowOf('shoulder_pan')).toHaveTextContent('STS3215')
    expect(rowOf('motor_driver')).toHaveTextContent('none yet')
  })

  it('shows the dashed empty box when there is nothing', async () => {
    await shown({})
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Robot parts · 0')
    expect(screen.getByText('No robot parts yet')).toBeInTheDocument()
    // The column headers stay; there is no row under them.
    expect(screen.getAllByRole('row')).toHaveLength(1)
  })

  it('reads each project its own rows', async () => {
    await shown(ARM)
    expect(api.listHardwareParts).toHaveBeenCalledWith('proj')
    expect(api.listExpectedParts).toHaveBeenCalledWith('proj')
    expect(api.listEntities).toHaveBeenCalledWith('proj', { type: 'physical_robot', limit: 100 })
  })

  it('says each status as a dot and a word', async () => {
    useDeviceStore.getState().setDevices('proj', [device('usb:A', { bound_to: 'r1' })])
    await shown(ARM)
    expect(within(rowOf('shoulder_pan')).getByText('Connected')).toBeInTheDocument()
    expect(rowOf('shoulder_pan').querySelector('.hw-dot-connected')).not.toBeNull()
    expect(within(rowOf('motor_driver')).getByText('Not connected')).toBeInTheDocument()
    expect(rowOf('motor_driver').querySelector('.hw-dot-not_connected')).not.toBeNull()
  })

  it('pulses the dot of a part whose device is being identified', async () => {
    useDeviceStore
      .getState()
      .setDevices('proj', [device('usb:A', { bound_to: 'r1', state: 'inspecting' })])
    await shown(ARM)
    expect(within(rowOf('shoulder_pan')).getByText('Identifying')).toBeInTheDocument()
    expect(rowOf('shoulder_pan').querySelector('.hw-dot-identifying')).toHaveClass('sol-pulse')
  })

  it('ignores device rows that belong to another project', async () => {
    useDeviceStore.getState().setDevices('other', [device('usb:A', { bound_to: 'r1' })])
    await shown(ARM)
    expect(within(rowOf('shoulder_pan')).getByText('Not connected')).toBeInTheDocument()
  })

  it('a part unplugged while the page is open reads when it left, not the old memory', async () => {
    const memory = machine([{ device_ref: 'usb:A', last_seen: '2026-11-14T00:00:00Z' }])
    const seen = { last_seen: '2026-11-14T00:00:00Z' }
    serve({ parts: [part('p1', 'known', { device_ref: 'usb:A' }), part('p2', 'new')] })
    api.listEntities.mockImplementation((_project: string, filters: { type?: string }) =>
      Promise.resolve(filters.type === 'machine' ? [memory] : [])
    )
    useDeviceStore
      .getState()
      .setDevices('proj', [device('usb:A', seen), device('usb:B', { ...seen, bound_to: 'p2' })])
    render(<PartsList projectId="proj" />)
    expect(
      await within(await screen.findByText('known').then(() => rowOf('known'))).findByText(
        'Connected'
      )
    ).toBeInTheDocument()

    act(() => useDeviceStore.getState().setDevices('proj', []))

    expect(within(rowOf('known')).getByText('Last seen just now')).toBeInTheDocument()
    // First plugged in during this visit: the page saw it itself, so it is not "Not connected".
    expect(within(rowOf('new')).getByText('Last seen just now')).toBeInTheDocument()
  })

  it('the Last seen words advance while the page sits open, and only while it is on show', async () => {
    serve({ parts: [part('p1', 'known')] })
    useDeviceStore
      .getState()
      .setDevices('proj', [device('usb:A', { last_seen: '2026-11-14T00:00:00Z', bound_to: 'p1' })])
    const { unmount } = render(<PartsList projectId="proj" />)
    await screen.findByText('Connected')
    const status = (words: string): HTMLElement => within(rowOf('known')).getByText(words)
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    const show = (state: DocumentVisibilityState): void => {
      visibility.mockReturnValue(state)
      act(() => void document.dispatchEvent(new Event('visibilitychange')))
    }
    vi.useFakeTimers()
    expect(vi.getTimerCount()).toBe(0)

    act(() => useDeviceStore.getState().setDevices('proj', []))
    expect(status('Last seen just now')).toBeInTheDocument()
    act(() => void vi.advanceTimersByTime(120_000))
    expect(status('Last seen 2 minutes ago')).toBeInTheDocument()

    // Out of sight the clock rests; back on show the words are true at once.
    show('hidden')
    expect(vi.getTimerCount()).toBe(0)
    vi.setSystemTime(Date.now() + 180_000)
    show('visible')
    expect(status('Last seen 5 minutes ago')).toBeInTheDocument()

    unmount()
    expect(vi.getTimerCount()).toBe(0)
    visibility.mockRestore()
  })

  describe('adding to the graph', () => {
    it('Add robot puts the robot in the graph through the route, then reads again', async () => {
      await shown(ARM)
      api.setInGraph.mockResolvedValue({ in_graph: true, updated: 2 })
      serve({ ...ARM, robots: [robot('r1', 'Rover arm')] })
      fireEvent.click(within(groupRow('Rover arm')).getByRole('button', { name: 'Add robot' }))
      expect(api.setInGraph).toHaveBeenCalledWith('proj', 'r1', true)
      await waitFor(() => expect(api.listHardwareParts).toHaveBeenCalledTimes(2))
      await waitFor(() => expect(groupRow('Rover arm')).toHaveTextContent('in graph'))
      expect(within(groupRow('Rover arm')).queryByRole('button')).not.toBeInTheDocument()
    })

    it('Add puts a lone part in the graph; a part on a robot has no button of its own', async () => {
      await shown(ARM)
      api.setInGraph.mockResolvedValue({ in_graph: true, updated: 1 })
      expect(within(rowOf('shoulder_pan')).queryByRole('button')).not.toBeInTheDocument()
      expect(rowOf('shoulder_pan')).toHaveTextContent('not yet')
      fireEvent.click(within(rowOf('motor_driver')).getByRole('button', { name: 'Add' }))
      expect(api.setInGraph).toHaveBeenCalledWith('proj', 'p2', true)
      await waitFor(() => expect(api.listHardwareParts).toHaveBeenCalledTimes(2))
    })

    it('shows the words of a refusal inline, and reads nothing again', async () => {
      await shown(ARM)
      const words = 'motor_driver is wired into a teammate’s hardware that isn’t in the graph yet.'
      api.setInGraph.mockRejectedValue(new ApiError(409, 'conflict', words))
      fireEvent.click(within(rowOf('motor_driver')).getByRole('button', { name: 'Add' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(words)
      expect(api.listHardwareParts).toHaveBeenCalledTimes(1)
      expect(within(rowOf('motor_driver')).getByRole('button', { name: 'Add' })).toBeEnabled()
    })

    it('says a refusal outside the table: a rowgroup holds rows only', async () => {
      await shown(ARM)
      api.setInGraph.mockRejectedValue(new ApiError(403, 'forbidden', 'Members only.'))
      fireEvent.click(within(rowOf('motor_driver')).getByRole('button', { name: 'Add' }))
      const alert = await screen.findByRole('alert')
      expect(alert.closest('[role="table"], [role="rowgroup"]')).toBeNull()
      const body = document.querySelector('[role="rowgroup"]')!
      expect([...body.children].every((child) => child.getAttribute('role') === 'row')).toBe(true)
    })

    it('shows a viewer the server’s own 403 words', async () => {
      await shown(ARM)
      api.setInGraph.mockRejectedValue(new ApiError(403, 'forbidden', 'Members only.'))
      fireEvent.click(within(groupRow('Rover arm')).getByRole('button', { name: 'Add robot' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Members only.')
    })
  })

  describe('described in your workspace, not seen yet', () => {
    const toggle = (): HTMLElement =>
      screen.getByRole('button', { name: /Described in your workspace, not seen yet/ })

    it('is hidden when the workspace describes nothing unseen', async () => {
      await shown(ARM)
      expect(screen.queryByText(/Described in your workspace/)).not.toBeInTheDocument()
    })

    it('starts collapsed with its count and the source summary', async () => {
      await shown({ ...ARM, expected: EXPECTED })
      expect(toggle()).toHaveAttribute('aria-expanded', 'false')
      expect(toggle()).toHaveTextContent('· 3')
      expect(toggle()).toHaveTextContent('from arm.yaml, Rover arm')
      expect(screen.queryByText('wrist_cam')).not.toBeInTheDocument()
    })

    it('expands into rows of the same grid that read Not seen yet', async () => {
      await shown({ ...ARM, expected: EXPECTED })
      fireEvent.click(toggle())
      expect(toggle()).toHaveAttribute('aria-expanded', 'true')
      const cam = rowOf('wrist_cam')
      expect(cam).toHaveClass('hw-grid')
      expect(cam).toHaveTextContent('sensor_msgs/Image')
      expect(cam).toHaveTextContent('none yet')
      expect(cam).toHaveTextContent('described only')
      expect(within(cam).getByText('Not seen yet')).toBeInTheDocument()
      expect(cam.querySelector('.hw-dot-not_seen')).not.toBeNull()
      expect(within(rowOf('gripper')).getAllByText('Rover arm').length).toBeGreaterThan(0)
      expect(screen.getByText('and 1 more')).toBeInTheDocument()
      fireEvent.click(toggle())
      expect(screen.queryByText('wrist_cam')).not.toBeInTheDocument()
    })

    it('draws every one of several identical described rows, each under its own key', async () => {
      const slot = { name: '', what: 'STS3215', robot_id: 'r1', source: 'Rover arm' }
      const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined)
      await shown({ ...ARM, expected: { expected: [slot, slot, slot], sources: [], more: 0 } })
      fireEvent.click(toggle())
      const table = screen.getByRole('table', { name: /Described in your workspace/ })
      expect(within(table).getAllByRole('row')).toHaveLength(3)
      expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/)
      errors.mockRestore()
    })

    it('a second identical described row that a later read brings is the one new row', async () => {
      const slot = { name: '', what: 'STS3215', robot_id: 'r1', source: 'Rover arm' }
      serve({ ...ARM, expected: { expected: [slot], sources: [], more: 0 } })
      const { rerender } = render(<PartsList projectId="proj" refreshKey={1} />)
      fireEvent.click(await screen.findByRole('button', { name: /Described in your workspace/ }))
      serve({ ...ARM, expected: { expected: [slot, slot], sources: [], more: 0 } })
      rerender(<PartsList projectId="proj" refreshKey={2} />)
      const table = screen.getByRole('table', { name: /Described in your workspace/ })
      await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(2))
      const rows = within(table).getAllByRole('row')
      expect(rows[0]).not.toHaveClass('local-row-in')
      expect(rows[1]).toHaveClass('local-row-in')
    })

    it('shows with no robot parts at all', async () => {
      await shown({ expected: EXPECTED })
      expect(screen.getByText('No robot parts yet')).toBeInTheDocument()
      expect(toggle()).toBeInTheDocument()
    })
  })

  describe('new rows', () => {
    it('animates nothing on the first read, then only the row that arrived', async () => {
      await shown(ARM)
      expect(document.querySelector('.local-row-in')).toBeNull()
      const more = [...ARM.parts, part('p3', 'elbow', { parent_id: 'r1' })]
      serve({ ...ARM, parts: more })
      api.setInGraph.mockResolvedValue({ in_graph: true, updated: 1 })
      fireEvent.click(within(rowOf('motor_driver')).getByRole('button', { name: 'Add' }))
      await screen.findByText('elbow')
      expect(rowOf('elbow')).toHaveClass('local-row-in')
      expect(rowOf('shoulder_pan')).not.toHaveClass('local-row-in')
      expect(rowOf('motor_driver')).not.toHaveClass('local-row-in')
      // It makes room at the end of its group: the rows that were there keep their order.
      const names = screen.getAllByRole('row').map((row) => row.textContent ?? '')
      expect(names.findIndex((text) => text.startsWith('shoulder_pan'))).toBeLessThan(
        names.findIndex((text) => text.startsWith('elbow'))
      )
    })

    it('reads again when the page says something changed', async () => {
      serve(ARM)
      const { rerender } = render(<PartsList projectId="proj" refreshKey={1} />)
      await screen.findByText('shoulder_pan')
      serve({ ...ARM, parts: [...ARM.parts, part('p3', 'elbow', { parent_id: 'r1' })] })
      rerender(<PartsList projectId="proj" refreshKey={2} />)
      expect(await screen.findByText('elbow')).toBeInTheDocument()
      expect(rowOf('elbow')).toHaveClass('local-row-in')
    })
  })

  describe('narrow widths', () => {
    it('carries the robot as a second line of the Part cell, for the widths that drop its column', async () => {
      await shown(ARM)
      const inline = rowOf('shoulder_pan').querySelector('.hw-robot-inline')
      expect(inline).toHaveTextContent('Rover arm')
      expect(inline).toHaveAttribute('aria-hidden', 'true')
      expect(rowOf('shoulder_pan').querySelector('.hw-robot')).toHaveTextContent('Rover arm')
    })

    it('moves Robot into the Part cell under 1100 px and makes rows two lines under 900 px', () => {
      const at = (query: string): string => css.slice(css.indexOf(query))
      const mid = at('@container hw-page (max-width: 1099px)')
      expect(mid).toMatch(/\.hw-robot\s*\{[^}]*display:\s*none/)
      expect(mid).toMatch(/\.hw-robot-inline\s*\{[^}]*display:\s*block/)
      const small = at('@container hw-page (max-width: 899px)')
      expect(small).toMatch(/\.hw-grid\s*\{[^}]*grid-template-columns:\s*1fr 1fr/)
      expect(small).toMatch(/\.hw-head\s*\{[^}]*display:\s*none/)
      expect(css).toMatch(/grid-template-columns:\s*1\.25fr 1\.2fr 0?\.9fr 1\.05fr 0?\.9fr/)
      expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i)
    })
  })

  it('says a failed read in the server’s words', async () => {
    api.listEntities.mockRejectedValue(new ApiError(403, 'forbidden', 'Not yours to read.'))
    api.listHardwareParts.mockResolvedValue([])
    api.listExpectedParts.mockResolvedValue(NOTHING)
    render(<PartsList projectId="proj" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not yours to read.')
  })
})
