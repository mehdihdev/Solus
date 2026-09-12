// The account anchor's card content (SOLUSDEV-250 P5): provider mark, login, document count.
import { expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Entity } from '../../lib/api/resources'
import { AccountNodeContent } from './AccountNodeContent'

const anchor: Entity = {
  id: 'account:c1',
  type: 'integration_account',
  domain: 'integration',
  name: 'octocat',
  source_key: null,
  properties: { provider: 'github', account_login: 'octocat', source_ids: ['s1'] }
}

it('shows the provider mark, the login and the document count', () => {
  const { container } = render(<AccountNodeContent entity={anchor} count={3} />)
  expect(screen.getByText('octocat')).toBeInTheDocument()
  expect(screen.getByText('3 documents')).toBeInTheDocument()
  expect(container.querySelector('[aria-hidden]')).not.toBeNull()
  expect(container.textContent).not.toContain('account:')
})

it('uses the singular for one document', () => {
  render(<AccountNodeContent entity={anchor} count={1} />)
  expect(screen.getByText('1 document')).toBeInTheDocument()
})
