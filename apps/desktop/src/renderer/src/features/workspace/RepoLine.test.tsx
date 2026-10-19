// A project's linked repo line (SOLUSDEV-317), shared by the project card and
// the project pane header: provider logo + repo, "+N" for more, nothing when none.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RepoLine } from './RepoLine'

describe('RepoLine', () => {
  it('shows the provider logo and the first repo, counting the rest', () => {
    render(
      <RepoLine
        repos={[
          { provider: 'github', repo: 'mehdihdev/elegoo_robot' },
          { provider: 'github', repo: 'mehdihdev/other' }
        ]}
      />
    )
    expect(screen.getByTestId('repo-logo-github')).toBeInTheDocument()
    expect(screen.getByText('mehdihdev/elegoo_robot')).toBeInTheDocument()
    expect(screen.getByText('+1')).toBeInTheDocument()
  })

  it('renders nothing without a repo', () => {
    const { container } = render(<RepoLine repos={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a hostile repo name as text', () => {
    render(<RepoLine repos={[{ provider: 'github', repo: '<img src=x onerror=alert(1)>' }]} />)
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('img[src="x"]')).toBeNull()
  })
})
