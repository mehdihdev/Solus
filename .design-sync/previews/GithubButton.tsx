import { Card, GithubButton, Mono, Wordmark } from '@solus/desktop'

const authorize = async (): Promise<{ error?: string }> => ({})

export function SignIn() {
  return (
    <div style={{ width: 320 }}>
      <GithubButton label="Continue with GitHub" onAuthorize={authorize} />
    </div>
  )
}

export function CreateAccount() {
  return (
    <div style={{ width: 320 }}>
      <GithubButton label="Sign up with GitHub" onAuthorize={authorize} />
    </div>
  )
}

export function InAuthCard() {
  return (
    <Card pad={24} style={{ width: 360 }}>
      <Wordmark size={14} />
      <div style={{ fontSize: 15, fontWeight: 600, marginTop: 20 }}>Sign in to Solus</div>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 6, lineHeight: 1.6 }}>
        Solus reads the repos you choose to connect. It never pushes to them without your
        confirmation.
      </div>
      <div style={{ marginTop: 18 }}>
        <GithubButton label="Continue with GitHub" onAuthorize={authorize} />
      </div>
      <div style={{ marginTop: 14, textAlign: 'center' }}>
        <Mono size={9.5}>GITHUB · GITLAB · EMAIL</Mono>
      </div>
    </Card>
  )
}
