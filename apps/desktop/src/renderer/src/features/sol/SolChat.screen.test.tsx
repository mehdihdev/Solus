// SOLUSDEV-324: "sees your screen" means SOL actually sees it. With the setting
// on and no circled region, a typed question carries the picture main took at
// summon (wireflow sol-window §D) — once; a circled region still wins; with the
// setting off nothing is asked for.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions } from './solChatStore'
import { SolChat } from './SolChat'
import { regionToScreenshot, screenToScreenshot, useSolWindowStore } from './solWindowStore'
import {
  SOL_REGION,
  SOL_STATE,
  fakeSolBridge,
  installSolBridge,
  uninstallSolBridge,
  type FakeSolBridge
} from './solWindow.fixtures'
import type { SolScreenPayload } from '../../../../main/capture/summonShot'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../../lib/api/search', () => ({ searchProject: vi.fn() }))
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

const SHOT: SolScreenPayload = {
  jpegBase64: '/9j/SCREEN',
  width: 1920,
  height: 1080,
  source: { app: 'Firefox', title: 'Gradescope' },
  capturedAt: 7
}

let bridge: FakeSolBridge & { takeScreen: ReturnType<typeof vi.fn> }

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolWindowStore.setState({ state: SOL_STATE, region: null })
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(solApi.listSolTurns).mockResolvedValue([])
  vi.mocked(resources.classifyQuery).mockReturnValue(new Promise(() => undefined))
  streamSolMessage.mockResolvedValue(undefined)
  bridge = Object.assign(fakeSolBridge(SOL_STATE), {
    takeScreen: vi.fn().mockResolvedValueOnce(SHOT).mockResolvedValue(null)
  })
  installSolBridge(bridge)
})

afterEach(() => uninstallSolBridge())

function ask(text: string): void {
  const box = screen.getByPlaceholderText(/Ask about a signal|What would you like to know/)
  fireEvent.change(box, { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

describe('SolChat summon picture', () => {
  it('maps the summon picture to a JPEG turn screenshot with no context image', () => {
    expect(screenToScreenshot(SHOT)).toEqual({
      media_type: 'image/jpeg',
      data: SHOT.jpegBase64,
      width: 1920,
      height: 1080,
      source: { app: 'Firefox', title: 'Gradescope' },
      context: null
    })
  })

  it('a typed question with the setting on carries the summon picture — once', async () => {
    render(<SolChat projectId="p1" />)
    ask("what's on my screen right now")
    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "what's on my screen right now",
          screenshot: screenToScreenshot(SHOT)
        })
      )
    )
    expect(bridge.takeScreen).toHaveBeenCalledTimes(1)
    expect(screen.getByText('screen attached')).toBeInTheDocument()
    await waitFor(() => expect(useSolSessionStore.getState().streaming).toBe(false))
    ask('and now?')
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(2))
    expect(streamSolMessage.mock.calls[1][0]).not.toHaveProperty('screenshot')
  })

  it('a circled region wins: the summon picture is not taken', async () => {
    useSolWindowStore.getState().setRegion(SOL_REGION)
    render(<SolChat projectId="p1" />)
    ask('is this symmetric?')
    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(
        expect.objectContaining({ screenshot: regionToScreenshot(SOL_REGION) })
      )
    )
    expect(bridge.takeScreen).not.toHaveBeenCalled()
  })

  it('setting off: nothing is asked for and the turn goes without pixels', async () => {
    useSolWindowStore.setState({ state: { ...SOL_STATE, screenIntelligence: false } })
    render(<SolChat projectId="p1" />)
    ask('hello')
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    expect(bridge.takeScreen).not.toHaveBeenCalled()
    expect(streamSolMessage.mock.calls[0][0]).not.toHaveProperty('screenshot')
  })

  it('a picture request that fails never loses the turn', async () => {
    bridge.takeScreen.mockReset().mockRejectedValue(new Error('ipc'))
    render(<SolChat projectId="p1" />)
    ask('hello')
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    expect(streamSolMessage.mock.calls[0][0]).not.toHaveProperty('screenshot')
  })
})
