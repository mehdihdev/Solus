import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Section, Row, InlineError, Callout, Kbd, StatusTag } from './settingsUi'

describe('Section', () => {
  it('renders the title, optional subtitle, and children', () => {
    render(
      <Section title="Profile" sub="Your identity">
        <div>body</div>
      </Section>
    )
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Your identity')).toBeInTheDocument()
    expect(screen.getByText('body')).toBeInTheDocument()
  })

  it('is a labelled region the sidebar can scroll to by id', () => {
    render(
      <Section id="sol" title="SOL" action={<button>Edit</button>}>
        <div>body</div>
      </Section>
    )
    const region = screen.getByRole('region', { name: 'SOL' })
    expect(region).toHaveAttribute('id', 'settings-sol')
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })
})

describe('Row', () => {
  it('renders a label and its control', () => {
    render(
      <Row label="Name">
        <button>edit</button>
      </Row>
    )
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('edit')).toBeInTheDocument()
  })

  it('puts the description under its label, not across the row', () => {
    render(
      <Row label="Usage data" description="Never your designs.">
        <button>toggle</button>
      </Row>
    )
    expect(screen.getByText('Never your designs.')).toBeInTheDocument()
  })
})

describe('Callout', () => {
  it('is a titled status region with its body and actions', () => {
    render(
      <Callout tone="warn" title="SOL can't see your screen" actions={<button>Open</button>}>
        Grant the permission.
      </Callout>
    )
    const box = screen.getByRole('group', { name: "SOL can't see your screen" })
    expect(box).toHaveTextContent('Grant the permission.')
    expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument()
  })
})

describe('Kbd and StatusTag', () => {
  it('render their text', () => {
    render(
      <>
        <Kbd>Ctrl</Kbd>
        <StatusTag tone="ok">Connected</StatusTag>
      </>
    )
    expect(screen.getByText('Ctrl').tagName).toBe('KBD')
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })
})

describe('InlineError', () => {
  it('renders nothing when no message', () => {
    const { container } = render(<InlineError message={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the message with an alert role when present', () => {
    render(<InlineError message="Could not save" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save')
  })
})
