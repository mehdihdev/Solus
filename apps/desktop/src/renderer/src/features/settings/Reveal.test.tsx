import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { Reveal, RevealList } from './Reveal'

describe('Reveal', () => {
  it('renders nothing while closed', () => {
    render(<Reveal open={false}>body</Reveal>)
    expect(screen.queryByText('body')).toBeNull()
  })

  it('expands its content in when opened', () => {
    const { rerender } = render(<Reveal open={false}>body</Reveal>)
    rerender(<Reveal open>body</Reveal>)
    expect(screen.getByText('body').closest('.settings-reveal')).not.toHaveAttribute('data-leaving')
  })

  it('plays the exit, then unmounts, when closed', async () => {
    const { rerender } = render(<Reveal open>body</Reveal>)
    rerender(<Reveal open={false}>body</Reveal>)
    await waitFor(() => expect(screen.queryByText('body')).toBeNull())
  })
})

describe('RevealList', () => {
  it('keeps a removed item until its exit has played', async () => {
    const renderItem = (s: string): React.JSX.Element => <span>{s}</span>
    const { rerender } = render(
      <RevealList items={['a', 'b']} keyOf={(s) => s} renderItem={renderItem} />
    )
    rerender(<RevealList items={['a']} keyOf={(s) => s} renderItem={renderItem} />)
    await waitFor(() => expect(screen.queryByText('b')).toBeNull())
    expect(screen.getByText('a')).toBeInTheDocument()
  })
})
