import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { api } from '../../lib/api/client'
import { listDocumentTree } from '../../lib/api/resources.documentTree'
import { DocumentTreeCatalog } from './documentTreeCatalog'
import { ServiceDocumentTree } from './ServiceDocumentTree'

vi.mock('../../lib/api/resources.documentTree', () => ({ listDocumentTree: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
it('expands folders once, selects only documents, and stops ancestor cycles', async () => {
  const folder = { id: 'f1', name: 'Robot', kind: 'folder' as const, node: 'folder:f1' }
  const document = { id: 'd1', name: 'Arm', kind: 'document' as const, node: null }
  vi.mocked(listDocumentTree)
    .mockResolvedValueOnce({ items: [folder], next_offset: null })
    .mockResolvedValueOnce({ items: [folder, document], next_offset: null })
  const select = vi.fn()
  render(
    <ServiceDocumentTree
      catalog={new DocumentTreeCatalog(api)}
      connectionId="c1"
      busy={false}
      added={() => false}
      select={select}
    />
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Robot' }))
  expect(select).not.toHaveBeenCalled()
  expect((await screen.findAllByRole('button', { name: 'Robot' }))[1]).toBeDisabled()
  await userEvent.click(await screen.findByRole('button', { name: 'Arm' }))
  expect(select).toHaveBeenCalledWith(document)
  await userEvent.click(screen.getAllByRole('button', { name: 'Robot' })[0])
  await userEvent.click(screen.getByRole('button', { name: 'Robot' }))
  expect(listDocumentTree).toHaveBeenCalledTimes(2)
})
