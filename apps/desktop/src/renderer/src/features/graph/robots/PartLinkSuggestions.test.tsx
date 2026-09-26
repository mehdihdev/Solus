import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { PartLinkSuggestions } from './PartLinkSuggestions'
import { proposePartLinks, decidePartLink } from '../../../lib/api/partSuggestions'
vi.mock('../../../lib/api/partSuggestions', () => ({
  proposePartLinks: vi.fn(),
  decidePartLink: vi.fn()
}))
const props = {
  projectId: 'p',
  partId: 'part',
  robots: [{ id: 'r', name: 'Rover' }],
  mode: 'Guide' as const,
  onChanged: vi.fn()
}
it('offers a named candidate only after explicit discovery and separate acceptance', async () => {
  vi.mocked(proposePartLinks).mockResolvedValue([
    { id: 's', robotId: 'r', confidence: 0.9, reason: 'Confirmed graph identity' }
  ])
  vi.mocked(decidePartLink).mockResolvedValue(undefined)
  render(<PartLinkSuggestions {...props} />)
  expect(proposePartLinks).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Find robot links' }))
  expect(await screen.findByText('Rover · 90%')).toBeInTheDocument()
  expect(decidePartLink).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Accept link to Rover' }))
  expect(await screen.findByText('Part attached.')).toBeInTheDocument()
  expect(decidePartLink).toHaveBeenCalledWith('p', 's', true)
  expect(props.onChanged).toHaveBeenCalledOnce()
})
it('discards discovery when project changes', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof proposePartLinks>>) => void
  vi.mocked(proposePartLinks).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done
      })
  )
  const view = render(<PartLinkSuggestions {...props} />)
  fireEvent.click(screen.getByRole('button', { name: 'Find robot links' }))
  view.rerender(<PartLinkSuggestions {...props} projectId="other" />)
  await act(async () => resolve([{ id: 's', robotId: 'r', confidence: 0.9, reason: null }]))
  expect(screen.queryByText('Rover · 90%')).not.toBeInTheDocument()
})
it('freezes an uncertain mutation instead of offering a duplicate acceptance', async () => {
  vi.mocked(proposePartLinks).mockResolvedValue([
    { id: 's', robotId: 'r', confidence: 0.9, reason: null }
  ])
  vi.mocked(decidePartLink).mockRejectedValue(new Error('lost response'))
  render(<PartLinkSuggestions {...props} />)
  fireEvent.click(screen.getByRole('button', { name: 'Find robot links' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Decline link to Rover' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('outcome could not be verified')
  expect(screen.getByRole('button', { name: 'Accept link to Rover' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Find robot links' })).toBeDisabled()
})
