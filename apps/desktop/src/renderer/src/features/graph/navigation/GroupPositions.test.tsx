import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { GraphNavigator, type GraphNavigatorProps } from './GraphNavigator'
import { useAuthStore } from '../../../store/authStore'

const props: GraphNavigatorProps = {
  projectId: 'p',
  entities: [
    {
      id: 'account:one',
      name: 'Account',
      type: 'integration_account',
      domain: 'integration',
      source_key: null
    }
  ],
  relations: [],
  positions: {},
  focusedId: null,
  onSelect: vi.fn(),
  onMove: vi.fn()
}
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'owner@example.test' } })
})
it('persists account dragging across remounts locally and never sends presentation IDs to the server', () => {
  const view = render(<GraphNavigator {...props} />)
  fireEvent.keyDown(screen.getByRole('button', { name: 'Move Account' }), { key: 'ArrowRight' })
  expect(props.onMove).not.toHaveBeenCalled()
  const x = screen.getByTestId('graph-node-account:one').getAttribute('data-x')
  view.unmount()
  render(<GraphNavigator {...props} />)
  expect(screen.getByTestId('graph-node-account:one')).toHaveAttribute('data-x', x)
  expect(x).not.toBe('0')
})
it('isolates local account groups by user and project, including A to B to A', () => {
  const view = render(<GraphNavigator {...props} />)
  fireEvent.keyDown(screen.getByRole('button', { name: 'Move Account' }), { key: 'ArrowRight' })
  const saved = screen.getByTestId('graph-node-account:one').getAttribute('data-x')
  act(() => useAuthStore.setState({ user: { email: 'other@example.test' } }))
  expect(screen.getByTestId('graph-node-account:one')).toHaveAttribute('data-x', '0')
  act(() => {
    useAuthStore.setState({ user: { email: 'owner@example.test' } })
  })
  expect(screen.getByTestId('graph-node-account:one')).toHaveAttribute('data-x', saved)
  view.rerender(<GraphNavigator {...props} projectId="other" />)
  expect(screen.getByTestId('graph-node-account:one')).toHaveAttribute('data-x', '0')
})
