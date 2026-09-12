import { useEffect, useRef, useState } from 'react'
import {
  getSourceView,
  listSourceRevisions,
  resetSourceView,
  selectSourceView,
  type SourceRevisionPage,
  type SourceView
} from '../../lib/api/resources.revisions'

interface Props {
  projectId: string
  sourceId: string
  activeSourceId?: string
  onChanged?: () => void
}
interface State {
  menu: SourceRevisionPage | null
  view: SourceView | null
  busy: boolean
  error: string | null
}
const EMPTY: State = { menu: null, view: null, busy: true, error: null }

/** Keyed inner state prevents a prior repository's controls surviving a selection change. */
export function SourceRevisionPicker(props: Props): React.JSX.Element {
  return <RevisionPicker key={`${props.projectId}:${props.sourceId}`} {...props} />
}

function RevisionPicker(props: Props): React.JSX.Element {
  const { projectId, sourceId, activeSourceId, onChanged } = props
  const [state, setState] = useState<State>(EMPTY)
  const generation = useRef(0)
  const changed = useRef(onChanged)
  useEffect(() => {
    changed.current = onChanged
  }, [onChanged])
  useEffect(() => {
    const request = ++generation.current
    void Promise.all([listSourceRevisions(projectId, sourceId), getSourceView(projectId, sourceId)])
      .then(([menu, view]) => {
        if (request === generation.current) {
          setState({ menu, view, busy: false, error: view.error })
          if (activeSourceId && view.source_id !== activeSourceId) changed.current?.()
        }
      })
      .catch(() => {
        if (request === generation.current)
          setState({ ...EMPTY, busy: false, error: 'Could not load repository branches.' })
      })
    return () => {
      generation.current += 1
    }
  }, [projectId, sourceId, activeSourceId])

  useRevisionPolling({
    projectId,
    sourceId,
    status: state.view?.status,
    busy: state.busy,
    generation,
    changed,
    setState
  })

  const choose = async (branch: string | null): Promise<void> => {
    const request = ++generation.current
    setState((current) => ({ ...current, busy: true, error: null }))
    try {
      const view =
        branch === null
          ? await resetSourceView(projectId, sourceId)
          : await selectSourceView(projectId, sourceId, branch)
      if (request !== generation.current) return
      setState((current) => ({ ...current, view, busy: false, error: view.error }))
      if (view.status === 'ready' || view.status === 'default') changed.current?.()
    } catch {
      if (request === generation.current)
        setState((current) => ({
          ...current,
          busy: false,
          error: 'Could not select this branch. Your previous view is unchanged.'
        }))
    }
  }
  const more = async (): Promise<void> => {
    if (!state.menu?.next_page) return
    const request = generation.current
    setState((current) => ({ ...current, busy: true }))
    try {
      const menu = await listSourceRevisions(projectId, sourceId, state.menu.next_page)
      if (request === generation.current) setState((current) => mergeBranchPage(current, menu))
    } catch {
      if (request === generation.current)
        setState((current) => ({ ...current, busy: false, error: 'Could not load more branches.' }))
    }
  }
  return <RevisionControls state={state} choose={choose} more={more} />
}

function mergeBranchPage(current: State, menu: SourceRevisionPage): State {
  const items = new Map(
    [...(current.menu?.items ?? []), ...menu.items].map((item) => [item.name, item])
  )
  return { ...current, busy: false, menu: { ...menu, items: [...items.values()] } }
}

interface PollingProps extends Pick<Props, 'projectId' | 'sourceId'> {
  status: SourceView['status'] | undefined
  busy: boolean
  generation: { current: number }
  changed: { current: Props['onChanged'] }
  setState: React.Dispatch<React.SetStateAction<State>>
}

function useRevisionPolling({
  projectId,
  sourceId,
  status,
  busy,
  generation,
  changed,
  setState
}: PollingProps): void {
  useEffect(() => {
    if (status !== 'pending' || busy) return
    let active = true
    const request = generation.current
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    const isCurrent = (): boolean => active && request === generation.current
    const poll = async (): Promise<void> => {
      try {
        const view = await getSourceView(projectId, sourceId)
        if (!isCurrent()) return
        setState((current) => ({ ...current, view, error: view.error }))
        if (view.status !== 'pending') {
          if (view.status === 'ready' || view.status === 'default') changed.current?.()
          return
        }
        attempts += 1
        if (attempts < 60)
          timer = setTimeout(() => {
            void poll()
          }, 2000)
        else
          setState((current) => ({
            ...current,
            error: 'Still preparing this branch. Reopen the repository to check progress.'
          }))
      } catch {
        if (isCurrent())
          setState((current) => ({
            ...current,
            error: 'Could not check branch preparation. Reopen the repository to retry.'
          }))
      }
    }
    timer = setTimeout(() => {
      void poll()
    }, 2000)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [projectId, sourceId, status, busy, generation, changed, setState])
}

interface ControlsProps {
  state: State
  choose: (branch: string | null) => Promise<void>
  more: () => Promise<void>
}

function BranchSelect({
  state,
  choose
}: Pick<ControlsProps, 'state' | 'choose'>): React.JSX.Element {
  const activeBranch = state.view?.branch ?? ''
  const pending = state.view?.status === 'pending'
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      Branch
      <select
        aria-label="Branch"
        value={activeBranch}
        disabled={state.busy || pending || !state.menu}
        onChange={(event) => {
          void choose(event.target.value)
        }}
      >
        {!state.menu?.items.some((item) => item.name === activeBranch) && (
          <option value={activeBranch}>{activeBranch || 'Project default'}</option>
        )}
        {state.menu?.items.map((item) => (
          <option key={item.name} value={item.name}>
            {item.name}
          </option>
        ))}
      </select>
    </label>
  )
}

function RevisionActions({ state, choose, more }: ControlsProps): React.JSX.Element {
  const pending = state.view?.status === 'pending'
  return (
    <>
      {state.menu?.next_page && (
        <button
          type="button"
          disabled={state.busy || pending}
          onClick={() => {
            void more()
          }}
        >
          Load more branches
        </button>
      )}
      {state.view && state.view.status !== 'default' && (
        <button
          type="button"
          disabled={state.busy}
          onClick={() => {
            void choose(null)
          }}
        >
          Use project default
        </button>
      )}
    </>
  )
}

function RevisionControls(props: ControlsProps): React.JSX.Element {
  const { state } = props
  if (state.menu && !state.menu.supported) return <></>
  return (
    <section aria-label="Repository branch" style={{ display: 'grid', gap: 8, padding: 12 }}>
      <BranchSelect state={state} choose={props.choose} />
      <small>Changes only your view and SOL context.</small>
      {state.view?.commit && <code>{state.view.commit.slice(0, 12)}</code>}
      {state.view?.status === 'pending' && (
        <span role="status">Preparing branch… Your current view remains available.</span>
      )}
      <RevisionActions {...props} />
      {state.error && <p role="alert">{state.error}</p>}
    </section>
  )
}
