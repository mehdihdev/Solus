// SOLUSDEV-252 S3: the SOL window surface (#/sol-window) — header (wordmark,
// mode badge, sees-screen dot, pin, close), the degraded-state status line,
// the region card / refused line, and the SolChat body behind the auth guard.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act, within } from '@testing-library/react'
import * as solApi from './solApi'
import { decideSolConfirmation } from '../../lib/api/resources'
import { resetSolChatSessions } from './solChatStore'
import { SolWindow } from './SolWindow'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore, WORKSPACE_STORAGE_KEY } from '../../store/workspaceStore'
import { useSolSessionStore } from './solSessionStore'
import { disconnectSolBridge, useSolWindowStore } from './solWindowStore'
import {
  SOL_REGION,
  SOL_STATE,
  fakeSolBridge,
  installSolBridge,
  uninstallSolBridge,
  type FakeSolBridge
} from './solWindow.fixtures'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  // Spread the real module: ArtifactCard (via SolChat) reads SOLUS_SECTIONS at load.
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn()
}))

const PLACEHOLDER = 'Ask about a signal, a change, a part…'
let bridge: FakeSolBridge

async function mount(): Promise<void> {
  render(<SolWindow />)
  // The mount's getState() resolves on a microtask; let the mirror land.
  await act(async () => undefined)
}

beforeEach(() => {
  localStorage.clear()
  disconnectSolBridge()
  useSolWindowStore.setState({ state: null, region: null })
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'a@b.dev' },
    accessToken: null,
    onboarded: true
  })
  useWorkspaceStore.setState({
    teamId: 't1',
    project: { id: 'p1', name: 'Rover MK2' },
    linked: true
  })
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  bridge = fakeSolBridge()
  installSolBridge(bridge)
})

afterEach(() => {
  disconnectSolBridge()
  uninstallSolBridge()
})

describe('SolWindow header', () => {
  it('asks main for the state on mount (flushes a queued region) and renders the chat', async () => {
    await mount()
    expect(bridge.getState).toHaveBeenCalledTimes(1)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toBeInTheDocument()
  })

  it('keeps the shared action mode control only in the composer', async () => {
    await mount()
    const badges = screen.getAllByRole('button', { name: 'SOL action mode' })
    // The composer remains the action-mode control.
    expect(badges).toHaveLength(1)
    for (const badge of badges) expect(badge).toHaveTextContent('Guide')
    fireEvent.click(badges[0])
    expect(bridge.setMode).toHaveBeenCalledWith('do')
    act(() => bridge.pushState({ ...SOL_STATE, actionMode: 'do' }))
    for (const badge of screen.getAllByRole('button', { name: 'SOL action mode' })) {
      expect(badge).toHaveTextContent('Build')
    }
  })

  it('follows a workspace selected in the main window', async () => {
    await mount()
    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        state: {
          teamId: 't2',
          project: { id: 'p2', name: 'Second robot' },
          linked: true
        },
        version: 0
      })
    )
    await act(async () =>
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: WORKSPACE_STORAGE_KEY,
          storageArea: localStorage
        })
      )
    )
    expect(useWorkspaceStore.getState().project?.id).toBe('p2')
  })

  it('shows "sees your screen" only while the setting is on', async () => {
    await mount()
    expect(screen.getByText('sees your screen')).toBeInTheDocument()
    act(() => bridge.pushState({ ...SOL_STATE, screenIntelligence: false }))
    expect(screen.queryByText('sees your screen')).not.toBeInTheDocument()
  })

  it('pin toggles always-on-top through the bridge; close closes the window', async () => {
    const close = vi.spyOn(window, 'close').mockImplementation(() => undefined)
    try {
      await mount()
      const pin = screen.getByRole('button', { name: 'Keep on top' })
      expect(pin).toHaveAttribute('aria-pressed', 'false')
      fireEvent.click(pin)
      expect(bridge.setAlwaysOnTop).toHaveBeenCalledWith(true)
      act(() => bridge.pushState({ ...SOL_STATE, alwaysOnTop: true }))
      expect(screen.getByRole('button', { name: 'Keep on top' })).toHaveAttribute(
        'aria-pressed',
        'true'
      )
      fireEvent.click(screen.getByRole('button', { name: 'Close' }))
      expect(close).toHaveBeenCalledTimes(1)
    } finally {
      close.mockRestore()
    }
  })

  it('the streaming indicator is one CSS class, present only while a turn streams', async () => {
    await mount()
    expect(document.querySelector('.sol-pulse')).toBeNull()
    act(() => useSolSessionStore.getState().setStreaming(true))
    expect(document.querySelectorAll('.sol-pulse')).toHaveLength(1)
  })
})

describe('SolWindow status line', () => {
  it('shows the hotkey summary and, when capture is degraded, its message as plain text', async () => {
    await mount()
    expect(screen.getByText('Hold Ctrl and circle to focus SOL on something')).toBeInTheDocument()
    act(() =>
      bridge.pushState({
        ...SOL_STATE,
        capture: {
          mode: 'needs-permission',
          message: 'Screen capture needs the Screen Recording permission — open Settings',
          settingsUrl: 'x-apple.systempreferences:com.apple.preference.security'
        }
      })
    )
    expect(
      screen.getByText('Screen capture needs the Screen Recording permission — open Settings')
    ).toBeInTheDocument()
    // Links stay text: nothing in the status line is an anchor.
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('renders no status line when nothing is degraded', async () => {
    await mount()
    act(() => bridge.pushState({ ...SOL_STATE, hotkeys: null }))
    expect(document.querySelector('.sol-window-status')).toBeNull()
  })
})

describe('SolWindow region card (wireflow §C)', () => {
  it('shows the crop when a region arrives', async () => {
    await mount()
    act(() => bridge.pushRegion(SOL_REGION))
    expect(screen.getByRole('img', { name: 'Circled screen region' })).toBeInTheDocument()
    expect(screen.getByText('Onshape — Bracket v3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'What do you think this is?' })).toBeInTheDocument()
  })

  it('with screen intelligence off, the gesture opened the window and the card is one line', async () => {
    await mount()
    act(() =>
      bridge.pushState({ ...SOL_STATE, screenIntelligence: false, lastRegionRefused: true })
    )
    expect(
      screen.getByText('SOL didn’t look — turn on SOL sees your screen in Settings to let it.')
    ).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Circled screen region' })).not.toBeInTheDocument()
  })
})

describe('SolWindow auth guard (the retired OrbWindow pattern)', () => {
  it('asks the user to sign in from the main window when unauthenticated', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null, onboarded: false })
    await mount()
    expect(screen.getByText(/Sign in from the main Solus window/)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(PLACEHOLDER)).not.toBeInTheDocument()
  })

  it('shows nothing but the spinner while the session resolves', async () => {
    useAuthStore.setState({ status: 'loading' })
    await mount()
    expect(screen.queryByPlaceholderText(PLACEHOLDER)).not.toBeInTheDocument()
  })
})

it('mounts Guide tasks and hides them when Build is selected', async () => {
  await mount()
  expect(screen.getByLabelText('Guide tool')).toBeInTheDocument()
  act(() => bridge.pushState({ ...SOL_STATE, actionMode: 'do' }))
  expect(screen.queryByLabelText('Guide tool')).not.toBeInTheDocument()
})

it('shows the fixture hole diff in the actual SOL window and requires an explicit decision', async () => {
  resetSolChatSessions()
  vi.mocked(solApi.createSolConversation).mockResolvedValue({
    id: 'c-hole'
  } as solApi.SolConversation)
  vi.mocked(decideSolConfirmation).mockResolvedValue({ ok: true } as Awaited<
    ReturnType<typeof decideSolConfirmation>
  >)
  vi.mocked(solApi.streamSolMessage).mockImplementation(async ({ onEvent }) => {
    onEvent({
      type: 'tool_confirmation',
      pending: {
        confirmationId: 'hole-card',
        tool: 'onshape.add_feature',
        summary: 'Add a 6 mm hole fixture',
        preview: [{ label: '6 mm hole fixture', before: null, after: 'new hole (diameter=6 mm)' }]
      }
    })
  })
  await mount()
  act(() => bridge.pushState({ ...SOL_STATE, actionMode: 'do' }))
  fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), {
    target: { value: 'Add a 6 mm hole' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  const card = await screen.findByLabelText('Action needs your approval')
  expect(within(card).getByText('new hole (diameter=6 mm)')).toBeInTheDocument()
  expect(decideSolConfirmation).not.toHaveBeenCalled()
  await act(async () => {
    fireEvent.click(within(card).getByRole('button', { name: 'Approve' }))
  })
  expect(decideSolConfirmation).toHaveBeenCalledWith('p1', 'hole-card', 'approve')
})
