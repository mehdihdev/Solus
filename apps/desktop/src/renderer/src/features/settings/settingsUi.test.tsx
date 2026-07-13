import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Section, Row, InlineError } from './settingsUi'

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
