// Local folder card on Home (SOLUSDEV-244; from the Project Overview hub,
// SOLUSDEV-164): select an existing directory or clone a repo, then
// open/unlink the linked folder. A long path is clipped with an ellipsis.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectFolderCard } from './ProjectFolderCard'
import { useProjectFolderStore } from './projectFolderStore'
import * as bridge from '../../lib/desktopBridge'

vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopFolderBridge: vi.fn() }
})

const pick = vi.fn()
const reveal = vi.fn()
const clone = vi.fn()
const openInVscode = vi.fn()
// The ~/.solus registry write-through (SOLUSDEV-166) rides on the same bridge.
const link = vi.fn()
const unlink = vi.fn()
const links = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  link.mockResolvedValue({ ok: true })
  unlink.mockResolvedValue({ ok: true })
  links.mockResolvedValue({})
  useProjectFolderStore.setState({ folders: {} })
  vi.mocked(bridge.getDesktopFolderBridge).mockReturnValue({
    pick,
    reveal,
    clone,
    openInVscode,
    link,
    unlink,
    links
  })
})

describe('ProjectFolderCard', () => {
  it('degrades honestly when not running under the desktop app', () => {
    vi.mocked(bridge.getDesktopFolderBridge).mockReturnValue(null)
    render(<ProjectFolderCard projectId="p1" />)
    expect(screen.getByText(/desktop app/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /select folder/i })).not.toBeInTheDocument()
  })

  it('offers select and clone when no folder is linked', () => {
    render(<ProjectFolderCard projectId="p1" />)
    expect(screen.getByRole('button', { name: /select folder/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /clone a repo/i })).toBeInTheDocument()
  })

  it('links a selected folder', async () => {
    pick.mockResolvedValue('/home/u/arm')
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
    await waitFor(() =>
      expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/arm')
    )
    expect(screen.getByText('/home/u/arm')).toBeInTheDocument()
  })

  it('ignores a cancelled folder pick', async () => {
    pick.mockResolvedValue(null)
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
    await waitFor(() => expect(pick).toHaveBeenCalled())
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  })

  it('opens a linked folder in VSCode', async () => {
    useProjectFolderStore.setState({ folders: { p1: { path: '/home/u/arm' } } })
    openInVscode.mockResolvedValue({ ok: true })
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /open with vscode/i }))
    expect(openInVscode).toHaveBeenCalledWith('/home/u/arm')
    expect(reveal).not.toHaveBeenCalled()
  })

  it('opens a linked folder in the file manager and unlinks', async () => {
    useProjectFolderStore.setState({ folders: { p1: { path: '/home/u/arm' } } })
    reveal.mockResolvedValue({ ok: true })
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /open folder/i }))
    expect(reveal).toHaveBeenCalledWith('/home/u/arm')
    expect(openInVscode).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /unlink/i }))
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  })

  it('clones a repo into a chosen parent and links the result', async () => {
    pick.mockResolvedValue('/home/u/code')
    clone.mockResolvedValue({ path: '/home/u/code/arm' })
    render(<ProjectFolderCard projectId="p1" suggestedRepoUrl="https://github.com/octo/arm.git" />)
    await userEvent.click(screen.getByRole('button', { name: /clone a repo/i }))
    // URL prefilled from the connected GitHub source.
    expect(screen.getByLabelText(/repository url/i)).toHaveValue('https://github.com/octo/arm.git')
    await userEvent.click(screen.getByRole('button', { name: /choose folder & clone/i }))
    await waitFor(() =>
      expect(clone).toHaveBeenCalledWith({
        repoUrl: 'https://github.com/octo/arm.git',
        parentDir: '/home/u/code'
      })
    )
    await waitFor(() =>
      expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/code/arm')
    )
  })

  it('shows a clone failure without linking', async () => {
    pick.mockResolvedValue('/home/u/code')
    clone.mockResolvedValue({ error: 'fatal: repository not found' })
    render(<ProjectFolderCard projectId="p1" suggestedRepoUrl="https://github.com/octo/x.git" />)
    await userEvent.click(screen.getByRole('button', { name: /clone a repo/i }))
    await userEvent.click(screen.getByRole('button', { name: /choose folder & clone/i }))
    expect(await screen.findByText(/repository not found/i)).toBeInTheDocument()
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  })
})

describe('ProjectFolderCard — long paths', () => {
  it('clips the path to one line ending in an ellipsis and keeps the full path in the title', () => {
    const long = '/Users/someone/Documents/robotics/teams/strider/rover-mk2/firmware/workspace'
    useProjectFolderStore.setState({ folders: { p1: { path: long } } })
    render(<ProjectFolderCard projectId="p1" />)
    const path = screen.getByTitle(long)
    expect(path).toHaveTextContent(long)
    expect(path).toHaveStyle({ textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' })
  })
})
