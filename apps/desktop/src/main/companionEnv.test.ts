// The companion's environment — CAD-02.
//
// This is why Fusion was invisible. `companion.ts` spawned with `env:
// process.env`, inheriting and adding nothing, so the companion's very first
// act — `config_from_env` — raised `SOLUS_COMPANION_URL is required` and the
// process exited. `onDown` then restarted it forever with the error discarded
// by `stdio: ['pipe','ignore','ignore']`, so a packaged build crash-looped in
// total silence.
//
// Two rules the companion enforces and both must be fed (companion/config.py):
//   1. the scheme must be `wss://` — only localhost may use `ws://`
//   2. the host must appear in SOLUS_COMPANION_ALLOWED_HOSTS
// Rule 2 exists because that host is where the user's bearer token gets sent.
import { describe, expect, it } from 'vitest'
import { companionEnv, companionWsUrl, findIntegrationsRoot } from './companionEnv'

describe('companionWsUrl', () => {
  const P = '01a0055b-a961-762a-9bcb-3f1eadca8eb0'

  it('derives wss from an https API base', () => {
    expect(companionWsUrl('https://api.solusforge.com/api/v1', P)).toBe(
      `wss://api.solusforge.com/api/v1/projects/${P}/bridge`
    )
  })

  it('keeps ws for a localhost dev API, which the companion allows', () => {
    expect(companionWsUrl('http://localhost:8000/api/v1', P)).toBe(
      `ws://localhost:8000/api/v1/projects/${P}/bridge`
    )
  })

  // THE REGRESSION. The URL used to be `<base>/bridge`, and the API's only
  // websocket route is `/api/v1/projects/{project_id}/bridge` — so nothing
  // matched, Starlette answered 403, and the companion retried forever. The
  // comment here even claimed the companion appended the project segment
  // itself; it does the opposite, parsing the id OUT of this URL
  // (`_BRIDGE_PATH_RE` in companion/config.py). The bridge could never connect.
  it('includes the project segment the API route requires', () => {
    const url = companionWsUrl('http://127.0.0.1:8000/api/v1', P)
    expect(url).toContain(`/projects/${P}/bridge`)
    expect(url).not.toBe('ws://127.0.0.1:8000/api/v1/bridge')
  })

  it('matches the shape the companion parses its project id out of', () => {
    // Mirrors companion/config.py `_BRIDGE_PATH_RE`; if this drifts, artifact
    // uploads silently disable themselves (api_endpoint_from_ws_url → None).
    const url = companionWsUrl('http://127.0.0.1:8000/api/v1', P) as string
    expect(new URL(url).pathname).toMatch(/^\/api\/v1\/projects\/[^/]+\/bridge$/)
  })

  it('returns null without a project, rather than a url that 403s', () => {
    // No project selected yet is a normal state at app start. Absent beats a
    // URL the server will reject on every retry.
    expect(companionWsUrl('http://localhost:8000/api/v1', null)).toBeNull()
  })

  it('refuses a project id that would escape the path', () => {
    // The id reaches here from the renderer. Path-shaped input must never
    // silently redirect the companion's dial target.
    expect(companionWsUrl('http://localhost:8000/api/v1', '../../evil')).toBeNull()
    expect(companionWsUrl('http://localhost:8000/api/v1', 'a/b')).toBeNull()
    expect(companionWsUrl('http://localhost:8000/api/v1', '')).toBeNull()
  })

  it('refuses plain http on a NON-loopback host rather than emitting ws://', () => {
    // The companion would reject this anyway; failing here makes the cause
    // visible instead of surfacing as a silent restart loop.
    expect(() => companionWsUrl('http://staging.example.com/api/v1', P)).toThrow(/wss/i)
  })

  it('returns null for a blank base rather than a malformed url', () => {
    expect(companionWsUrl('', P)).toBeNull()
  })
})

describe('companionEnv', () => {
  const P = '01a0055b-a961-762a-9bcb-3f1eadca8eb0'

  it('supplies the two variables without which the companion cannot start', () => {
    const env = companionEnv({ PATH: '/bin' }, 'https://api.solusforge.com/api/v1', {
      projectId: P
    })

    expect(env.SOLUS_COMPANION_URL).toBe(`wss://api.solusforge.com/api/v1/projects/${P}/bridge`)
    expect(env.SOLUS_COMPANION_ALLOWED_HOSTS).toContain('api.solusforge.com')
  })

  it('omits the url with no project, so the companion idles instead of 403-looping', () => {
    const env = companionEnv({ PATH: '/bin' }, 'https://api.solusforge.com/api/v1')

    expect(env.SOLUS_COMPANION_URL).toBeUndefined()
  })

  it('always allows loopback so a dev build works alongside a staging URL', () => {
    const env = companionEnv({}, 'https://api.solusforge.com/api/v1', { projectId: P })

    expect(env.SOLUS_COMPANION_ALLOWED_HOSTS).toContain('localhost')
    expect(env.SOLUS_COMPANION_ALLOWED_HOSTS).toContain('127.0.0.1')
  })

  it('preserves the inherited environment', () => {
    const env = companionEnv({ PATH: '/bin', HOME: '/home/x' }, 'https://api.solusforge.com/api/v1')

    expect(env.PATH).toBe('/bin')
    expect(env.HOME).toBe('/home/x')
  })

  it('lets an explicit override win, for pointing a build at another API', () => {
    const env = companionEnv(
      { SOLUS_COMPANION_URL: 'wss://other.example.com/bridge' },
      'https://api.solusforge.com/api/v1'
    )

    expect(env.SOLUS_COMPANION_URL).toBe('wss://other.example.com/bridge')
  })

  it('omits the url when it cannot be derived, rather than passing a broken one', () => {
    // Absent is better than malformed: the companion's own error message names
    // the missing variable, which is the actionable failure.
    const env = companionEnv({}, '')

    expect(env.SOLUS_COMPANION_URL).toBeUndefined()
  })
})

// SOLUSDEV-166 (ADR-034): the fourth of the same kind. Read in two places,
// previously written nowhere — the Altium fork fails closed without it.
describe('companionEnv — workspace', () => {
  const P = '01a0055b-a961-762a-9bcb-3f1eadca8eb0'

  it('passes the registry-derived workspace to the companion', () => {
    const env = companionEnv({}, 'https://api.solusforge.com/api/v1', {
      projectId: P,
      workspace: '/Users/alex/robots/rover'
    })

    expect(env.SOLUS_COMPANION_WORKSPACE).toBe('/Users/alex/robots/rover')
  })

  it('leaves the variable ABSENT with no workspace, so forks fail closed', () => {
    const env = companionEnv({}, 'https://api.solusforge.com/api/v1', { projectId: P })

    expect(env.SOLUS_COMPANION_WORKSPACE).toBeUndefined()
  })

  it('leaves the variable absent for a null workspace (project not linked)', () => {
    const env = companionEnv({}, 'https://api.solusforge.com/api/v1', {
      projectId: P,
      workspace: null
    })

    expect(env.SOLUS_COMPANION_WORKSPACE).toBeUndefined()
  })

  it('lets an explicit inherited override win, like the other variables', () => {
    const env = companionEnv(
      { SOLUS_COMPANION_WORKSPACE: '/explicit/override' },
      'https://api.solusforge.com/api/v1',
      { projectId: P, workspace: '/from/registry' }
    )

    expect(env.SOLUS_COMPANION_WORKSPACE).toBe('/explicit/override')
  })
})

// The SAME failure as the URL above, one variable along, and it cost another
// debugging session: config.py falls back to a vendored `mcp/` tree next to
// `sys.executable`, which is right for the packaged binary and impossible in
// dev (`.venv/bin/python3`). So `SOLUS_COMPANION_INTEGRATIONS_ROOT is required`
// killed the companion at every spawn and the only UI symptom was a bridge pill
// reading "offline".
describe('findIntegrationsRoot', () => {
  const tree = (...present: string[]) => {
    const set = new Set(present)
    return (p: string): boolean => set.has(p)
  }

  it('finds the tree from the app directory', () => {
    const exists = tree('/repo/integrations/mcp')
    expect(findIntegrationsRoot('/repo/apps/desktop', exists)).toBe('/repo/integrations/mcp')
  })

  it('finds it from a build output directory too', () => {
    // Not assuming app.getAppPath() is exactly <repo>/apps/desktop: under
    // electron-vite it can be the out/ dir, and hardcoding the hop count would
    // silently resolve to nothing.
    const exists = tree('/repo/integrations/mcp')
    expect(findIntegrationsRoot('/repo/apps/desktop/out/main', exists)).toBe(
      '/repo/integrations/mcp'
    )
  })

  it('returns null when no ancestor has the tree', () => {
    // Null is the honest answer, and it must stay null: inventing a path would
    // turn a packaging mistake into a companion running with zero servers.
    expect(findIntegrationsRoot('/somewhere/else', tree())).toBeNull()
  })

  it('stops at the filesystem root instead of looping', () => {
    expect(findIntegrationsRoot('/', tree())).toBeNull()
  })
})

describe('companionEnv — integrations root', () => {
  it('sets the root when one was resolved', () => {
    const env = companionEnv({}, 'http://127.0.0.1:8000/api/v1', {
      integrationsRoot: '/repo/integrations/mcp'
    })

    expect(env.SOLUS_COMPANION_INTEGRATIONS_ROOT).toBe('/repo/integrations/mcp')
  })

  it('lets an inherited value win, so a build can point elsewhere', () => {
    const env = companionEnv(
      { SOLUS_COMPANION_INTEGRATIONS_ROOT: '/custom/mcp' },
      'http://127.0.0.1:8000/api/v1',
      { integrationsRoot: '/repo/integrations/mcp' }
    )

    expect(env.SOLUS_COMPANION_INTEGRATIONS_ROOT).toBe('/custom/mcp')
  })

  it('leaves the variable ABSENT when nothing resolved', () => {
    // A packaged build passes null and uses its binary-adjacent tree. Setting a
    // guessed path here would replace the companion's actionable error with a
    // silent zero-server run.
    const env = companionEnv({}, 'http://127.0.0.1:8000/api/v1', { integrationsRoot: null })

    expect(env.SOLUS_COMPANION_INTEGRATIONS_ROOT).toBeUndefined()
  })

  it('is unchanged when the argument is omitted', () => {
    const env = companionEnv({}, 'http://127.0.0.1:8000/api/v1')

    expect(env.SOLUS_COMPANION_INTEGRATIONS_ROOT).toBeUndefined()
  })
})
