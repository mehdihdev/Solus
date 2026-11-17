// SOLUSDEV-326 P3: the Hardware page assembled (docs/wireflows/hardware-onboarding.md): header,
// card slot, Done so far and parts list, in the design's three states. SOL is the shell's sidebar:
// the page mounts no SOL panel of its own.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OpenCard } from '@solus/shared-types'
import type { ExpectedParts } from '../../lib/api/hardware'
import { decideSolConfirmation } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { SolChat } from '../sol/useSolChat'
import { fetchOpenCards } from './cardsApi'
import { useDeviceStore } from './deviceStore'
import { HardwareScreen } from './HardwareScreen'
import { openCard } from './testing/cards'
import { device } from './testing/fixtures'
import { part, robot } from './testing/parts'

const api = vi.hoisted(() => ({
  listEntities: vi.fn(),
  listHardwareParts: vi.fn(),
  listExpectedParts: vi.fn(),
  clearDeviceDismissals: vi.fn(),
  decideSolConfirmation: vi.fn(),
  useSolChat: vi.fn()
}))
vi.mock('./cardsApi', () => ({ fetchOpenCards: vi.fn() }))
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  listEntities: api.listEntities,
  decideSolConfirmation: api.decideSolConfirmation
}))
vi.mock('../../lib/api/hardware', async (original) => ({
  ...(await original<typeof import('../../lib/api/hardware')>()),
  listHardwareParts: api.listHardwareParts,
  listExpectedParts: api.listExpectedParts,
  clearDeviceDismissals: api.clearDeviceDismissals
}))
vi.mock('../sol/useSolChat', () => ({ useSolChat: api.useSolChat }))

const NOTHING: ExpectedParts = { expected: [], sources: [], more: 0 }
const DESCRIBED: ExpectedParts = {
  expected: [{ name: 'wrist_cam', what: 'sensor_msgs/Image', robot_id: null, source: 'arm.yaml' }],
  sources: ['arm.yaml'],
  more: 7
}
const START = 'Plug in your hardware'
const IDLE = 'Nothing needs you right now. Anything you plug in shows up here.'

const chat = {
  items: [] as unknown[],
  streaming: false,
  working: null as string | null,
  send: vi.fn(),
  sendNotice: vi.fn(),
  answer: vi.fn(),
  cardDecided: vi.fn(),
  resumeCard: vi.fn()
}

function serve(world: {
  robots?: ReturnType<typeof robot>[]
  parts?: ReturnType<typeof part>[]
  expected?: ExpectedParts
  card?: OpenCard | null
}): void {
  api.listEntities.mockImplementation((_project: string, filters: { type?: string }) =>
    Promise.resolve(filters.type === 'physical_robot' ? (world.robots ?? []) : [])
  )
  api.listHardwareParts.mockResolvedValue(world.parts ?? [])
  api.listExpectedParts.mockResolvedValue(world.expected ?? NOTHING)
  vi.mocked(fetchOpenCards).mockResolvedValue({ card: world.card ?? null, queued: 0 })
}

const tick = (ms = 0): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)))

/** Mounted, read, and past the slot's 450 ms arrival guard. */
async function mount(): Promise<ReturnType<typeof render>> {
  const view = render(<HardwareScreen />)
  await tick()
  await tick(450)
  return view
}
const press = (name: string): boolean => fireEvent.click(screen.getByRole('button', { name }))

const ARM = robot('r1', 'Rover arm', { in_graph: false })
const servo = (id: string, name: string): ReturnType<typeof part> =>
  part(id, name, { parent_id: 'r1', model: 'STS3215' })
const SERVOS = [servo('p1', 'shoulder_pan'), servo('p2', 'shoulder_lift'), servo('p3', 'elbow')]

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  Object.assign(chat, { items: [], streaming: false, working: null })
  chat.send.mockResolvedValue(true)
  chat.sendNotice.mockResolvedValue(true)
  chat.answer.mockResolvedValue(true)
  chat.resumeCard.mockResolvedValue(undefined)
  api.useSolChat.mockImplementation(() => ({ ...chat }) as unknown as SolChat)
  api.clearDeviceDismissals.mockResolvedValue({ dismissed: [] })
  vi.mocked(decideSolConfirmation).mockResolvedValue({ ok: true })
  useDeviceStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover project' } })
  serve({})
})
afterEach(() => {
  vi.useRealTimers()
})

describe('the page', () => {
  it('draws the header, the slot, Done so far and the list', async () => {
    await mount()
    expect(screen.getByRole('heading', { level: 1, name: 'Hardware' })).toBeInTheDocument()
    expect(
      screen.getByText('Robot parts Solus knows about, and whether each one is connected.')
    ).toBeInTheDocument()
    expect(screen.getByTestId('card-slot').parentElement?.style.marginTop).toBe('20px')
    expect(screen.getByTestId('done-so-far')).toHaveTextContent('')
    expect(screen.getByRole('heading', { level: 2, name: /Robot parts/ })).toBeInTheDocument()
  })

  it('mounts no SOL panel of its own: SOL is the shell’s sidebar, and the slot’s chat is the Hardware surface', async () => {
    await mount()
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(screen.queryByRole('button', { name: /SOL panel/ })).toBeNull()
    expect(api.useSolChat).toHaveBeenCalledWith('p1', 'hardware')
  })

  it('is the container its narrow-width rules measure, so they follow the room beside the sidebar', async () => {
    const view = await mount()
    expect(view.container.firstElementChild).toHaveClass('hw-page')
    const here = dirname(fileURLToPath(import.meta.url))
    const css = readFileSync(join(here, 'partsList.css'), 'utf8')
    expect(css).toMatch(/\.hw-page\s*\{[^}]*container:\s*hw-page\s*\/\s*inline-size/)
    expect(css).toContain('@container hw-page (max-width: 1099px)')
    expect(css).toContain('@container hw-page (max-width: 899px)')
    expect(css).not.toMatch(/@media\s*\(max-width/)
  })

  it('without a project draws the header and reads nothing', async () => {
    useWorkspaceStore.setState({ project: null })
    await mount()
    expect(screen.getByRole('heading', { level: 1, name: 'Hardware' })).toBeInTheDocument()
    expect(fetchOpenCards).not.toHaveBeenCalled()
    expect(api.listHardwareParts).not.toHaveBeenCalled()
  })
})

describe('A1: nothing connected yet', () => {
  it('shows the start card, "No robot parts yet" and the described group', async () => {
    serve({ expected: DESCRIBED })
    await mount()
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect a robot computer' })).toBeInTheDocument()
    expect(screen.getByText('No robot parts yet')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Described in your workspace, not seen yet/ })
    ).toHaveTextContent('· 8')
    expect(screen.getByTestId('done-so-far')).toHaveTextContent('')
  })

  it('the start card sends its sentence to SOL once, then the slot goes idle', async () => {
    await mount()
    press('Connect a robot computer')
    await tick(800)
    expect(chat.send).toHaveBeenCalledExactlyOnceWith(
      'Connect a robot computer',
      'do',
      undefined,
      undefined,
      undefined,
      undefined
    )
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
    expect(screen.getByText(IDLE)).toBeInTheDocument()
  })

  it('the start card leaves on the press, so a second press mid-turn cannot send again', async () => {
    let settle: (sent: boolean) => void = () => undefined
    chat.send.mockReturnValue(new Promise<boolean>((resolve) => (settle = resolve)))
    const view = await mount()
    press('Connect a robot computer')
    // The turn is live and no tool has run yet: the slot has no working line to hide the card.
    Object.assign(chat, { streaming: true, working: null })
    view.rerender(<HardwareScreen />)
    await tick(800)
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Connect a robot computer' })).toBeNull()
    expect(chat.send).toHaveBeenCalledOnce()
    settle(true)
    await tick()
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
  })

  it('the start card stays when its sentence never reached SOL', async () => {
    chat.send.mockResolvedValue(false)
    await mount()
    press('Connect a robot computer')
    await tick(800)
    expect(chat.send).toHaveBeenCalledOnce()
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
  })

  it('the start card comes back when its send throws', async () => {
    chat.send.mockRejectedValue(new Error('offline'))
    await mount()
    press('Connect a robot computer')
    await tick(800)
    expect(chat.send).toHaveBeenCalledOnce()
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
  })

  it('"Ask again" goes to the expired card’s own conversation and leaves the start card alone', async () => {
    const expiring = openCard({
      conversation_id: 'conv7',
      expires_at: new Date(Date.now() + 7000).toISOString()
    })
    serve({ card: expiring })
    await mount()
    // The 5 s read still lists it; it expires on show at 7 s, and the next read no longer does.
    await tick(6000)
    vi.mocked(fetchOpenCards).mockResolvedValue({ card: null, queued: 0 })
    await tick(5000)
    press('Ask again')
    await tick(800)
    expect(chat.send).toHaveBeenCalledExactlyOnceWith(
      'Please ask me again about the card that expired.',
      'do',
      undefined,
      undefined,
      undefined,
      { conversationId: 'conv7' }
    )
    // The list is empty and the person never used the start card: it is still offered.
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
  })

  it('an open card takes the slot before the start card', async () => {
    serve({ card: openCard() })
    await mount()
    expect(screen.getByRole('heading', { name: 'Found: 3 servos on a USB adapter' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
  })
})

describe('A2: midway', () => {
  const PI = openCard(
    { confirmation_id: 'c2', conversation_id: 'conv7', tool: 'hardware.connect_host' },
    {
      kind: 'approval',
      title: 'Approve: connect the Raspberry Pi',
      primary: 'Approve',
      receipt: 'Raspberry Pi connected'
    }
  )

  it('lists the robot group and its parts, and no start card', async () => {
    serve({ robots: [ARM], parts: SERVOS, card: PI })
    await mount()
    const table = screen.getByRole('table', { name: 'Robot parts' })
    expect(within(table).getAllByText('Rover arm').length).toBeGreaterThan(0)
    expect(within(table).getByText('· 3 parts')).toBeInTheDocument()
    expect(within(table).getByText('elbow')).toBeInTheDocument()
    expect(screen.queryByText('No robot parts yet')).toBeNull()
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
  })

  it('an approval adds its receipt to Done so far, continues SOL and reads the list again', async () => {
    serve({ robots: [ARM], parts: SERVOS, card: PI })
    await mount()
    const reads = api.listHardwareParts.mock.calls.length
    vi.mocked(fetchOpenCards).mockResolvedValue({ card: null, queued: 0 })
    press('Approve')
    await tick(800)
    expect(decideSolConfirmation).toHaveBeenCalledExactlyOnceWith('p1', 'c2', 'approve')
    expect(screen.getByTestId('done-so-far')).toHaveTextContent(
      'Done so far: Raspberry Pi connected'
    )
    expect(chat.resumeCard).toHaveBeenCalledExactlyOnceWith(PI)
    // The thread's row for this card is decided too (the SOL page shares the session).
    expect(chat.cardDecided).toHaveBeenCalledExactlyOnceWith('c2', 'approve')
    expect(api.listHardwareParts.mock.calls.length).toBeGreaterThan(reads)
    // Parts exist and the start card was never asked for: the slot rests on the idle line.
    expect(screen.getByText(IDLE)).toBeInTheDocument()
  })

  it('a question card is answered through the chat, in the conversation it was asked in', async () => {
    const question = openCard({ confirmation_id: 'q1', conversation_id: 'conv7', tool: 'ask_user' })
    serve({ robots: [ARM], parts: SERVOS, card: question })
    await mount()
    press('Not now')
    await tick(800)
    expect(chat.answer).toHaveBeenCalledExactlyOnceWith(
      'q1',
      1,
      undefined,
      'conv7',
      undefined,
      expect.any(Function)
    )
    expect(decideSolConfirmation).not.toHaveBeenCalled()
  })

  describe('an edited device offer', () => {
    const offer = openCard(
      { confirmation_id: 'c9', conversation_id: 'conv7' },
      { field: { label: 'Robot name', value: 'Rover arm' } }
    )
    const edit = async (): Promise<void> => {
      serve({ robots: [ARM], parts: SERVOS, card: offer })
      await mount()
      fireEvent.change(screen.getByLabelText('Robot name'), { target: { value: 'Arm B' } })
      press('Add')
      await tick(800)
    }

    it('sends one request, the answer, in the card’s conversation: no decision, no typed turn', async () => {
      await edit()
      expect(chat.answer).toHaveBeenCalledExactlyOnceWith(
        'c9',
        0,
        'Arm B',
        'conv7',
        undefined,
        expect.any(Function)
      )
      expect(decideSolConfirmation).not.toHaveBeenCalled()
      expect(chat.send).not.toHaveBeenCalled()
      expect(chat.cardDecided).not.toHaveBeenCalled()
      expect(chat.resumeCard).not.toHaveBeenCalled()
    })

    it('stays out of the slot until the answer turn went, files nothing, and comes back when it failed', async () => {
      let settle: (sent: boolean) => void = () => undefined
      let admit: () => void = () => undefined
      chat.answer.mockImplementation(
        (...args: unknown[]) =>
          new Promise<boolean>((resolve) => {
            admit = args[5] as () => void
            settle = resolve
          })
      )
      await edit()
      await tick(5000)
      expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
      expect(screen.getByText(IDLE)).toBeInTheDocument()
      act(() => admit())
      expect(screen.getByTestId('done-so-far')).toHaveTextContent('')
      await act(async () => settle(false))
      expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
    })
  })

  describe('an answered question that waits behind a live turn', () => {
    const question = openCard(
      { confirmation_id: 'q1', conversation_id: 'conv7', tool: 'ask_user' },
      { primary: 'Yes', secondary: 'No', receipt: 'Cameras named' }
    )
    /** The answer turn, held: the server goes on listing the question as open meanwhile. */
    function held(): { admit: () => void; settle: (sent: boolean) => void } {
      const turn: { admit: () => void; settle: (sent: boolean) => void } = {
        admit: () => undefined,
        settle: () => undefined
      }
      chat.answer.mockImplementation(
        (...args: unknown[]) =>
          new Promise<boolean>((resolve) => {
            turn.admit = args[5] as () => void
            turn.settle = resolve
          })
      )
      return turn
    }

    it('cannot be answered twice: it stays out of the slot until the answer went', async () => {
      const turn = held()
      serve({ robots: [ARM], parts: SERVOS, card: question })
      await mount()
      press('Yes')
      await tick(800)
      await tick(5000)
      expect(screen.queryByRole('button', { name: 'Yes' })).toBeNull()
      expect(screen.getByText(IDLE)).toBeInTheDocument()
      await act(async () => turn.settle(true))
      await tick(5000)
      expect(screen.queryByRole('button', { name: 'Yes' })).toBeNull()
      expect(chat.answer).toHaveBeenCalledOnce()
    })

    it('comes back when the answer never reached SOL', async () => {
      const turn = held()
      serve({ robots: [ARM], parts: SERVOS, card: question })
      await mount()
      press('Yes')
      await tick(800)
      expect(screen.queryByRole('button', { name: 'Yes' })).toBeNull()
      await act(async () => turn.settle(false))
      expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument()
    })

    it('adds its receipt to Done so far only once the answer turn was admitted', async () => {
      const turn = held()
      serve({ robots: [ARM], parts: SERVOS, card: question })
      await mount()
      press('Yes')
      await tick(800)
      expect(screen.getByTestId('done-so-far')).toHaveTextContent('')
      act(() => turn.admit())
      expect(screen.getByTestId('done-so-far')).toHaveTextContent('Done so far: Cameras named')
      // An answer that fails before it is admitted files nothing.
      await act(async () => turn.settle(false))
      press('No')
      await tick(800)
      await act(async () => turn.settle(false))
      expect(screen.getByTestId('done-so-far')).toHaveTextContent('Done so far: Cameras named')
    })
  })

  it('shows what SOL is doing from the chat, and reads the open card when a frame lands', async () => {
    serve({ robots: [ARM], parts: SERVOS })
    const view = await mount()
    const reads = vi.mocked(fetchOpenCards).mock.calls.length
    Object.assign(chat, {
      streaming: true,
      working: 'Reading the USB adapter',
      items: [{ trace: [{}], confirmations: [] }]
    })
    view.rerender(<HardwareScreen />)
    await tick()
    expect(screen.getByTestId('slot-working')).toHaveTextContent('Reading the USB adapter')
    expect(vi.mocked(fetchOpenCards).mock.calls.length).toBeGreaterThan(reads)
  })
})

describe('A3: all connected', () => {
  it('every part reads Connected, a lone part sits under "Not on a robot"', async () => {
    useDeviceStore.getState().setDevices('p1', [device('usb_serial:A', { bound_to: 'r1' })])
    serve({
      robots: [ARM],
      parts: [...SERVOS, part('p9', 'motor_driver', { model: 'your board' })],
      card: openCard(
        { confirmation_id: 'c3', tool: 'hardware.set_in_graph' },
        { title: 'Rover arm is set up', primary: 'Add to workspace graph', secondary: null }
      )
    })
    await mount()
    expect(screen.getByRole('heading', { name: 'Rover arm is set up' })).toBeVisible()
    const table = screen.getByRole('table', { name: 'Robot parts' })
    expect(within(table).getAllByText('Connected')).toHaveLength(3)
    expect(within(table).getByText('Not on a robot')).toBeInTheDocument()
    expect(within(table).getByText('motor_driver')).toBeInTheDocument()
  })
})

describe('+ Add hardware', () => {
  it('clears the "Not now" list and shows the start card again', async () => {
    serve({ robots: [ARM], parts: SERVOS })
    await mount()
    expect(screen.queryByRole('heading', { name: START })).toBeNull()
    press('+ Add hardware')
    await tick()
    expect(api.clearDeviceDismissals).toHaveBeenCalledExactlyOnceWith('p1')
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
  })

  it('shows the start card even when the list could not be cleared', async () => {
    api.clearDeviceDismissals.mockRejectedValue(new Error('machine_unknown'))
    serve({ robots: [ARM], parts: SERVOS })
    await mount()
    press('+ Add hardware')
    await tick()
    expect(screen.getByRole('heading', { name: START })).toBeInTheDocument()
  })
})

describe('the plug-in notice', () => {
  it('announces a device that arrives while the page is open, once, after 2 s', async () => {
    useDeviceStore.getState().setDevices('p1', [])
    await mount()
    act(() => useDeviceStore.getState().setDevices('p1', [device('usb_serial:B')]))
    await tick(1999)
    expect(chat.sendNotice).not.toHaveBeenCalled()
    await tick(1)
    expect(chat.sendNotice).toHaveBeenCalledExactlyOnceWith('usb_serial:B')
  })

  it('announces on opening what was already plugged in and the device the toast was about, each once a session', async () => {
    useDeviceStore
      .getState()
      .setDevices('p1', [
        device('usb_serial:A'),
        device('usb_serial:B'),
        device('usb_serial:C', { dismissed: true })
      ])
    useDeviceStore.getState().owe(['usb_serial:B'])
    const page = await mount()
    await tick(2000)
    expect(chat.sendNotice.mock.calls).toEqual([['usb_serial:A'], ['usb_serial:B']])
    // Opened again in the same session: nothing more.
    page.unmount()
    await mount()
    await tick(5000)
    expect(chat.sendNotice).toHaveBeenCalledTimes(2)
  })

  it('"+ Add hardware" announces again what is plugged in and still unclaimed', async () => {
    useDeviceStore
      .getState()
      .setDevices('p1', [device('usb_serial:A'), device('usb_serial:B', { bound_to: 'r1' })])
    await mount()
    await tick(5000)
    expect(chat.sendNotice).toHaveBeenCalledExactlyOnceWith('usb_serial:A')
    press('+ Add hardware')
    await tick(2000)
    expect(chat.sendNotice.mock.calls).toEqual([['usb_serial:A'], ['usb_serial:A']])
  })
})
