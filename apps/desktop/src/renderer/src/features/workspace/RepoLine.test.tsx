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
    expect(screen.getByTestId('repo-logo-github')).toHaveClass('logo-mono')
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

  it('links the repo to its GitHub page when asked, opening outside the app', () => {
    render(<RepoLine repos={[{ provider: 'github', repo: 'mehdihdev/elegoo_robot' }]} linked />)
    const link = screen.getByRole('link', { name: /mehdihdev\/elegoo_robot/ })
    expect(link).toHaveAttribute('href', 'https://github.com/mehdihdev/elegoo_robot')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('links GitLab repos to gitlab.com', () => {
    render(<RepoLine repos={[{ provider: 'gitlab', repo: 'group/sub/fw' }]} linked />)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://gitlab.com/group/sub/fw')
  })

  it('is plain text by default, for other providers, and for anything not owner/repo shaped', () => {
    const first = render(<RepoLine repos={[{ provider: 'github', repo: 'org/fw' }]} />)
    expect(screen.queryByRole('link')).toBeNull()
    first.unmount()
    const second = render(<RepoLine repos={[{ provider: 'bitbucket', repo: 'org/fw' }]} linked />)
    expect(screen.queryByRole('link')).toBeNull()
    second.unmount()
    render(<RepoLine repos={[{ provider: 'github', repo: '../evil?x=javascript:1' }]} linked />)
    expect(screen.queryByRole('link')).toBeNull()
  })
})
