// The account anchor's sidebar (SOLUSDEV-250 P5): provider mark + login, the anchor's
// documents from the merged snapshot (selectable → reveal), and "Add another" opening
// Add › Integrations. No id is ever printed.
import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Entity, Relation } from '../../../lib/api/resources'
import { AccountSidebar } from './AccountSidebar'

const anchor: Entity = {
  id: 'account:c1',
  type: 'integration_account',
  domain: 'integration',
  name: 'octocat',
  source_key: null,
  properties: { provider: 'github', account_login: 'octocat', source_ids: ['s1'] }
}
const repo: Entity = {
  id: '0199-repo',
  type: 'repository',
  domain: 'code',
  name: 'rover-firmware',
  source_key: 'github:rover',
  source_id: 's1'
}
const other: Entity = { ...repo, id: '0199-other', name: 'unrelated' }
const relations: Relation[] = [
  { id: 'account:c1:0199-repo', type: 'contains', from_entity_id: anchor.id, to_entity_id: repo.id }
]

function mount(): { onReveal: ReturnType<typeof vi.fn>; onOpenAdd: ReturnType<typeof vi.fn> } {
  const onReveal = vi.fn()
  const onOpenAdd = vi.fn()
  render(
    <AccountSidebar
      entity={anchor}
      entities={[repo, other, anchor]}
      relations={relations}
      onReveal={onReveal}
      onOpenAdd={onOpenAdd}
    />
  )
  return { onReveal, onOpenAdd }
}

it('shows the login and only the anchor’s documents, with no id printed', () => {
  mount()
  expect(screen.getByRole('heading', { name: /octocat/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'rover-firmware' })).toBeInTheDocument()
  expect(screen.queryByText('unrelated')).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/account:|0199-/)
})

it('reveals a document on select', async () => {
  const { onReveal } = mount()
  await userEvent.click(screen.getByRole('button', { name: 'rover-firmware' }))
  expect(onReveal).toHaveBeenCalledWith(repo.id)
})

it('opens Add › Integrations from "Add another"', async () => {
  const { onOpenAdd } = mount()
  await userEvent.click(screen.getByRole('button', { name: /add another/i }))
  expect(onOpenAdd).toHaveBeenCalledWith('service')
})
