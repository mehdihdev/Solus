import { useEffect, useState, useSyncExternalStore } from 'react'
import { useWorkspaceSessionGeneration } from '../graph/workspaceSession'
import { useSolWindowStore } from '../sol/solWindowStore'
import { GuidePanel } from './GuidePanel'
import { listGuides, type GuideSummary } from './guideApi'

type Surface = 'browser' | 'native' | 'scriptable'
// Trusted application presentation metadata. A KB control's toolbar/menu surface
// describes placement, never whether the application is browser/native/scriptable.
const TOOLS: Record<string, { label: string; surface: Surface; version: string }> = {
  onshape: { label: 'Onshape', surface: 'browser', version: '1.0' },
  kicad: { label: 'KiCad', surface: 'native', version: '' },
  code: { label: 'Code / commands', surface: 'scriptable', version: '' }
}

let modeGeneration = 0
const modeListeners = new Set<() => void>()
useSolWindowStore.subscribe((next, previous) => {
  if (next.state?.actionMode !== previous.state?.actionMode) {
    modeGeneration += 1
    modeListeners.forEach((listener) => listener())
  }
})
function subscribeMode(listener: () => void): () => void {
  modeListeners.add(listener)
  return () => {
    modeListeners.delete(listener)
  }
}
export function GuideTasks(): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  const mode = useSyncExternalStore(subscribeMode, () => modeGeneration)
  return <TaskPicker key={`${generation}:${mode}`} />
}

function TaskPicker(): React.JSX.Element {
  const [tool, setTool] = useState('')
  const [version, setVersion] = useState('')
  const [task, setTask] = useState('')
  const [selection, setSelection] = useState(0)
  const [lookupGeneration, setLookupGeneration] = useState(0)
  const [tasks, setTasks] = useState<GuideSummary[]>([])
  const [status, setStatus] = useState('')
  const metadata = TOOLS[tool]
  useEffect(() => {
    let live = true
    if (!tool || !/^\d+(?:\.\d+){0,2}$/.test(version)) return
    const controller = new AbortController()
    void listGuides(tool, version, undefined, controller.signal)
      .then((rows) => {
        if (live) {
          setTasks(rows)
          setStatus(rows.length ? '' : 'No authored walkthrough covers this version yet.')
        }
      })
      .catch(() => {
        if (live) setStatus('Could not load walkthroughs. Choose the tool again to retry.')
      })
    return () => {
      live = false
      controller.abort()
    }
  }, [tool, version, lookupGeneration])
  return (
    <section
      aria-label="Guide walkthroughs"
      style={{ padding: 12, overflowY: 'auto', maxHeight: '55%' }}
    >
      <label>
        Guide tool{' '}
        <select
          value={tool}
          onChange={(event) => {
            const next = event.target.value
            setLookupGeneration((value) => value + 1)
            setTasks([])
            setTool(next)
            setVersion(TOOLS[next]?.version ?? '')
            setTask('')
            setStatus(TOOLS[next]?.version ? 'Loading walkthroughs…' : '')
          }}
        >
          <option value="">Choose a tool</option>
          {Object.entries(TOOLS).map(([id, value]) => (
            <option key={id} value={id}>
              {value.label}
            </option>
          ))}
        </select>
      </label>
      {metadata && (
        <>
          {tool === 'onshape' ? (
            <p>Knowledge compatibility convention 1.x; this is not the Onshape release version.</p>
          ) : (
            <label>
              Installed tool version{' '}
              <input
                value={version}
                placeholder="For example, 9.0"
                onChange={(event) => {
                  setLookupGeneration((value) => value + 1)
                  setTasks([])
                  setStatus(
                    /^\d+(?:\.\d+){0,2}$/.test(event.target.value) ? 'Loading walkthroughs…' : ''
                  )
                  setVersion(event.target.value)
                  setTask('')
                }}
              />
            </label>
          )}
          {metadata.surface === 'scriptable' && (
            <p>Commands are instructions to copy and review. Guide never runs them.</p>
          )}
          {metadata.surface === 'native' && (
            <p>
              The native window location is unavailable until explicitly requested. Guidance stays
              in this panel.
            </p>
          )}
          {!version && (
            <p>
              Not sure where that is in this version. Enter the installed version to resolve known
              controls.
            </p>
          )}
          {status && <p role="status">{status}</p>}
          <label>
            Guide task{' '}
            <select
              value={task}
              onChange={(event) => {
                setSelection((value) => value + 1)
                setTask(event.target.value)
              }}
            >
              <option value="">Choose a walkthrough</option>
              {tasks.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          {task && (
            <GuidePanel
              key={`${tool}:${version}:${task}:${selection}`}
              guideId={task}
              tool={tool}
              version={version}
              presentation={metadata.surface}
            />
          )}
        </>
      )}
    </section>
  )
}
