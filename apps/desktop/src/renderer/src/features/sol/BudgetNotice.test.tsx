// SOLUSDEV-321 P1-T6: the notice that SOL stopped on a budget. It sits above the router's own
// loop_limit error, so the person learns WHICH ceiling the turn hit, not just that it ended.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BudgetNotice } from './BudgetNotice'

describe('BudgetNotice', () => {
  it('says which ceiling stopped SOL, with what it used and the cap', () => {
    render(<BudgetNotice budget={{ limit: 'tool_calls', used: 24, cap: 24 }} />)
    expect(screen.getByText('SOL stopped: tool_calls budget reached (24/24)')).toBeInTheDocument()
  })

  it('is announced politely, as a status', () => {
    render(<BudgetNotice budget={{ limit: 'web_searches', used: 1, cap: 1 }} />)
    expect(screen.getByRole('status')).toHaveTextContent(
      'SOL stopped: web_searches budget reached (1/1)'
    )
  })

  it('renders nothing before a ceiling is reached', () => {
    const { container } = render(<BudgetNotice budget={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders text only', () => {
    render(<BudgetNotice budget={{ limit: '<img src=x onerror=alert(1)>', used: 1, cap: 1 }} />)
    expect(document.querySelector('img, [onerror]')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('<img src=x onerror=alert(1)>')
  })
})
