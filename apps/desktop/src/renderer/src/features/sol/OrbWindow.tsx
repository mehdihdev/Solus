// SOLX-02: the surface of the detached always-on-top window — the same
// renderer loaded at the #/orb hash route by main/sol-window/solWindow.ts.
// Compact chrome: a draggable header (the window is frameless), the OrbChat
// body scoped to the persisted workspace project, and a "Return to app"
// hand-back over the attach invoke. Session and project state rehydrate from
// the shared localStorage; signing in stays a main-window flow.
import { Mono } from '../../components/ui/Mono'
import { SolOrb } from '../../components/ui/SolOrb'
import { Spinner } from '../../components/ui/Spinner'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { OrbChat } from './OrbChat'
import { selectOrbPulse, useOrbStore } from './orbStore'
import { getSolWindowBridge } from './solWindowBridge'

const DRAG: React.CSSProperties = { WebkitAppRegion: 'drag' } as React.CSSProperties
const NO_DRAG: React.CSSProperties = { WebkitAppRegion: 'no-drag' } as React.CSSProperties

function Centered({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
        fontSize: 12,
        color: 'var(--mut)',
        textAlign: 'center'
      }}
    >
      {children}
    </div>
  )
}

export function OrbWindow(): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const project = useWorkspaceStore((s) => s.project)
  const pulse = useOrbStore(selectOrbPulse)

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        border: '1px solid var(--bd)',
        boxSizing: 'border-box',
        overflow: 'hidden'
      }}
    >
      <div
        style={{
          ...DRAG,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 10px',
          borderBottom: '1px solid var(--bd)',
          background: 'var(--sur)'
        }}
      >
        <SolOrb size={18} pulse={pulse} />
        <Mono size={9.5} color="var(--tx)">
          SOL
        </Mono>
        {project && <Mono size={9.5}>{project.name}</Mono>}
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => void getSolWindowBridge()?.attach()}
          style={{
            ...NO_DRAG,
            background: 'transparent',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            color: 'var(--mut)',
            fontSize: 10.5,
            padding: '3px 8px',
            cursor: 'pointer'
          }}
        >
          Return to app
        </button>
      </div>
      {status === 'loading' ? (
        <Centered>
          <Spinner size={18} />
        </Centered>
      ) : status === 'unauthenticated' ? (
        <Centered>Sign in from the main Solus window to use SOL here.</Centered>
      ) : (
        <OrbChat projectId={project?.id ?? null} layout="panel" />
      )}
    </div>
  )
}
