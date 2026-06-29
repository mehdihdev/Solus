// GitHub auth button, ported from GithubBtn in TestDesign/app/auth.jsx.
// Wired to a real action (Supabase OAuth, or dev bypass when unconfigured).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'

type State = 'idle' | 'authorizing' | 'error'

interface GithubButtonProps {
  label: string
  onAuthorize: () => Promise<{ error?: string }>
}

export function GithubButton({ label, onAuthorize }: GithubButtonProps): React.JSX.Element {
  const [state, setState] = useState<State>('idle')
  const [error, setError] = useState<string | null>(null)

  const click = async (): Promise<void> => {
    if (state === 'authorizing') return
    setState('authorizing')
    setError(null)
    const result = await onAuthorize()
    if (result.error) {
      setState('error')
      setError(result.error)
    }
    // On success the auth state change navigates away; leave the spinner.
  }

  return (
    <>
      <Button
        kind="soft"
        onClick={click}
        style={{ width: '100%', padding: '10px 0', fontSize: 13 }}
      >
        {state === 'authorizing' ? (
          <>
            <Spinner /> Authorizing with GitHub…
          </>
        ) : (
          <>
            <Icons.github size={15} /> {label}
          </>
        )}
      </Button>
      {error && (
        <div style={{ fontSize: 11, color: 'var(--err)', marginTop: 8, textAlign: 'center' }}>
          {error}
        </div>
      )}
    </>
  )
}
