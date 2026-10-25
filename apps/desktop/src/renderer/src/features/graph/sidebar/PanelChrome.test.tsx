import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import { NodePanelFooter, NodePanelHeader, panelLabel } from './PanelChrome'

const board: Entity = {
  id: 'b1',
  type: 'pcb_board',
  domain: 'electrical',
  name: 'Main board rev B',
  source_key: 'kicad:board'
}
const anchor: Entity = {
  id: 'account:c1',
  type: 'integration_account',
  domain: 'integration',
  name: 'ana',
  source_key: null,
  properties: { provider: 'onshape' }
}

describe('panelLabel', () => {
  it('names an account anchor as a source and other nodes by source type or domain', () => {
    expect(panelLabel(anchor, null)).toBe('SOURCE · ONSHAPE')
    expect(panelLabel(board, 'kicad')).toBe('KICAD · PCB BOARD')
    expect(panelLabel(board, null)).toBe('ELECTRICAL · PCB BOARD')
    expect(panelLabel({ ...board, type: 'solus_config' }, null)).toBe('ELECTRICAL · ROOT + PROJECT')
  })
})

describe('NodePanelHeader', () => {
  it('renders the label, title and only the facts it was given', () => {
    const onClose = vi.fn()
    render(
      <NodePanelHeader
        entity={board}
        label="KICAD · PCB BOARD"
        title={board.name}
        meta={{ editedAgo: '2h ago' }}
        onClose={onClose}
      />
    )
    expect(screen.getByRole('heading', { level: 2, name: 'Main board rev B' })).toBeInTheDocument()
    expect(screen.getByText('KICAD · PCB BOARD')).toBeInTheDocument()
    expect(screen.getByText('LAST EDITED')).toBeInTheDocument()
    expect(screen.getByText('2h ago')).toBeInTheDocument()
    expect(screen.queryByText('AUTHORED BY')).toBeNull()
    expect(screen.getByRole('banner')).toHaveAttribute('data-domain', 'electrical')
    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('omits the heading, the facts grid and the close button when not given', () => {
    render(<NodePanelHeader entity={board} label="X" />)
    expect(screen.queryByRole('heading')).toBeNull()
    expect(document.querySelector('.node-panel-meta')).toBeNull()
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('NodePanelFooter', () => {
  it('is a plain strip for its actions', () => {
    render(
      <NodePanelFooter>
        <button type="button">One</button>
        <button type="button">Two</button>
      </NodePanelFooter>
    )
    expect(document.querySelector('.node-panel-footer')?.children).toHaveLength(2)
  })
})
