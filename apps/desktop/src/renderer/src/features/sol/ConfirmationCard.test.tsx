// The approval surface. What matters here is that a user can see WHAT they are
// approving — a bare tool name is not meaningful consent — and that a failed
// decision never looks like a successful one.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { ConfirmationCard } from './ConfirmationCard'

const PENDING: PendingConfirmation = {
  confirmationId: 'c1',
  tool: 'onshape.set_variable',
  summary: 'Change a Variable Studio value (onshape.set_variable) with name=’width’',
  preview: [{ label: 'width', before: '100 mm', after: '120 mm' }]
}

describe('ConfirmationCard', () => {
  confirmationDescriptionTests()
  confirmationDecisionsTests()
  confirmationExactValuesTests()
})

describe('a decision the server REFUSED', () => {
  // The bug this guards: the decide route answers HTTP 200 with `ok:false` for
  // STALE / EXPIRED / already-decided / tool-failed, so nothing throws on its
  // own and the card was cleared exactly as if the action had run. For
  // `put_featurescript`, which replaces a whole Feature Studio, a false "it
  // worked" is the worst outcome this flow can produce.
  const refusal = (): Error => {
    const error = new Error(
      'What this action would do has changed since it was shown to you. Nothing was applied.'
    )
    error.name = 'ConfirmationRefused'
    return error
  }

  it('keeps the card and says the approval cannot be retried', async () => {
    const onDecide = vi.fn().mockRejectedValue(refusal())
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    })

    expect(screen.getByText(/Nothing was applied/)).toBeInTheDocument()
    expect(screen.getByText(/can’t be retried/)).toBeInTheDocument()
    // It must NOT claim the action is still waiting: every refusal status is
    // terminal, so re-approving can only ever earn "already decided".
    expect(screen.queryByText(/still waiting for you/)).not.toBeInTheDocument()
  })

  it('disables both buttons, because the confirmation is spent', async () => {
    const onDecide = vi.fn().mockRejectedValue(refusal())
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    })

    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  })

  it('leaves a TRANSPORT failure retryable, because the action is still parked', async () => {
    const onDecide = vi.fn().mockRejectedValue(new Error('Network request failed'))
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    })

    expect(screen.getByText(/still waiting for you/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).not.toBeDisabled()
  })
})

describe('review layout', () => {
  confirmationPreviewExpansionTests()
  confirmationPreviewContentsTests()
})

function confirmationDescriptionTests(): void {
  it('shows the diff, not just the action name', () => {
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    expect(screen.getByText('width')).toBeInTheDocument()
    expect(screen.getByText('100 mm')).toBeInTheDocument()
    expect(screen.getByText('120 mm')).toBeInTheDocument()
  })

  it('names the tool so the user knows what is acting', () => {
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    expect(screen.getByText('onshape.set_variable')).toBeInTheDocument()
  })

  it('renders any tool’s rows — it is not Onshape-specific', () => {
    const firmware: PendingConfirmation = {
      confirmationId: 'c2',
      tool: 'arduino.flash',
      summary: 'Flash firmware to the connected board',
      preview: [{ label: 'sketch', before: 'blink v3', after: 'blink v4' }]
    }

    render(<ConfirmationCard pending={firmware} onDecide={vi.fn()} />)

    expect(screen.getByText('arduino.flash')).toBeInTheDocument()
    expect(screen.getByText('blink v4')).toBeInTheDocument()
  })

  it('says so when a tool could not describe its change', () => {
    // Rare now — the server falls back to the arguments — but if even that is
    // absent the card must not imply a diff was checked.
    render(<ConfirmationCard pending={{ ...PENDING, preview: [] }} onDecide={vi.fn()} />)

    expect(screen.getByText(/could not describe its change/)).toBeInTheDocument()
  })
}

function confirmationDecisionsTests(): void {
  it('approves through the callback', async () => {
    const onDecide = vi.fn(async () => {})
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(onDecide).toHaveBeenCalledWith('approve'))
  })

  it('rejects through the callback', async () => {
    // The card reports the decision and stops there; the host removes it. A
    // local "done" state here would claim an outcome the card cannot observe.
    const onDecide = vi.fn(async () => {})
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(onDecide).toHaveBeenCalledWith('reject'))
  })

  it('cannot be double-submitted while a decision is in flight', async () => {
    let release = (): void => {}
    const onDecide = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        })
    )
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    await act(async () => release())
  })

  it('a failed decision does not look like a successful one', async () => {
    const onDecide = vi.fn(async () => {
      throw new Error('offline')
    })
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    // ...and the user can try again.
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })
}

function confirmationExactValuesTests(): void {
  it('never shouts the value — case is part of what executes', () => {
    // Onshape variable names and FeatureScript unit tokens are case-sensitive.
    // A card that paints `#WIDTH * 2` shows an expression that is not the one
    // being approved.
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    for (const text of ['width', '100 mm', '120 mm']) {
      const node = screen.getByText(text)
      expect(getComputedStyle(node).textTransform).not.toBe('uppercase')
    }
  })

  it('does not assume the action is a design change', () => {
    // The same gate carries CAD edits, robot control and shell commands.
    const shell: PendingConfirmation = {
      confirmationId: 'c3',
      tool: 'delphiscript.run_script',
      summary: 'Executes a script on the customer machine',
      preview: [{ label: 'command', before: null, after: 'rm -rf /tmp/build' }]
    }

    const { container } = render(<ConfirmationCard pending={shell} onDecide={vi.fn()} />)

    expect(container.textContent).not.toMatch(/your design/i)
    expect(screen.getByText('rm -rf /tmp/build')).toBeInTheDocument()
  })

  it('shows the reason a decision was refused, not a generic apology', async () => {
    const onDecide = vi.fn(async () => {
      throw new Error('What this action would do has changed since it was shown to you.')
    })
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/has changed since it was shown/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })
}

function confirmationPreviewExpansionTests(): void {
  it('keeps large previews collapsed with visible actions and all rows available', async () => {
    const onDecide = vi.fn()
    const preview = Array.from({ length: 40 }, (_, index) => ({
      label: `Change ${index + 1}`,
      before: `Before ${index}`,
      after: `After ${index}`
    }))
    render(<ConfirmationCard pending={{ ...PENDING, preview }} onDecide={onDecide} />)
    expect(screen.getByText(PENDING.summary)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeVisible()
    expect(screen.getByText('After 39')).not.toBeVisible()
    await userEvent.click(screen.getByText('Review all 40 changes'))
    expect(screen.getByText('After 39')).toBeVisible()
    expect(screen.getAllByRole('listitem')).toHaveLength(40)
    expect(screen.getByRole('region', { name: 'Complete proposed changes' })).toHaveAttribute(
      'tabindex',
      '0'
    )
    expect(onDecide).not.toHaveBeenCalled()
  })

  it('expands short previews by default', () => {
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)
    expect(screen.getByText('Review 1 change').closest('details')).toHaveAttribute('open')
    expect(screen.getByText('120 mm')).toBeVisible()
  })

  it('collapses a single multiline patch without removing its complete contents', async () => {
    const patch = '@@ -1 +1 @@\n-    run()\n+\trun()\n'
    render(
      <ConfirmationCard
        pending={{ ...PENDING, preview: [{ label: 'Patch', before: null, after: patch }] }}
        onDecide={vi.fn()}
      />
    )
    const value = screen.getByText(/@@ -1/)
    expect(value.textContent).toBe(patch)
    expect(value).not.toBeVisible()
    await userEvent.click(screen.getByText('Review 1 change'))
    expect(value).toBeVisible()
  })
}

function confirmationPreviewContentsTests(): void {
  it('keeps the summary visible while technical details can be expanded without deciding', async () => {
    const onDecide = vi.fn()
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)
    expect(screen.getByRole('heading', { name: 'Review this action' })).toBeVisible()
    expect(screen.getByText(PENDING.summary)).toBeVisible()
    expect(screen.getByText(PENDING.tool)).not.toBeVisible()
    await userEvent.click(screen.getByText('Technical details'))
    expect(screen.getByText(PENDING.tool)).toBeVisible()
    expect(screen.getByText(PENDING.confirmationId)).toBeVisible()
    expect(onDecide).not.toHaveBeenCalled()
  })

  it('distinguishes unavailable values from empty strings and labels both sides', () => {
    render(
      <ConfirmationCard
        pending={{ ...PENDING, preview: [{ label: 'MixedCase', before: null, after: '' }] }}
        onDecide={vi.fn()}
      />
    )
    expect(screen.getByText('Before')).toBeVisible()
    expect(screen.getByText('After')).toBeVisible()
    expect(screen.getByText('Not provided')).toBeVisible()
    expect(screen.getByText('Empty string')).toBeVisible()
    expect(screen.getByText('MixedCase')).toBeVisible()
  })

  it('preserves complete long values and their case', () => {
    const value = `#MixedCase ${'AbC/'.repeat(300)} tail`
    render(
      <ConfirmationCard
        pending={{
          ...PENDING,
          preview: [{ label: 'LongValue', before: 'OldValue', after: value }]
        }}
        onDecide={vi.fn()}
      />
    )
    const rendered = screen.getByText(value)
    expect(rendered.textContent).toBe(value)
    expect(getComputedStyle(rendered).textTransform).not.toBe('uppercase')
  })

  it('preserves significant whitespace in a staged code diff', () => {
    const patch = '@@ -1 +1 @@\n-    run()\n+\trun()\n'
    const { container } = render(
      <ConfirmationCard
        pending={{
          ...PENDING,
          tool: 'code.git_commit',
          preview: [{ label: 'Complete staged diff', before: null, after: patch }]
        }}
        onDecide={vi.fn()}
      />
    )
    expect(
      Array.from(container.querySelectorAll('.confirmation-card__value')).some(
        (element) => element.textContent === patch
      )
    ).toBe(true)
  })
}
