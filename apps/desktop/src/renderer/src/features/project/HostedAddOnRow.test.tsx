// The hosted add-on affordance (SOLUSDEV-168). What matters here is that the
// state shown is the SERVER's, that the disclosure is rendered verbatim, and
// that "subscribed?" is answered by asking the backend rather than by trusting
// a redirect — the vendor documents that its own success signal is not
// trustworthy.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IntegrationHosted, Source } from '../../lib/api/resources'
import * as resources from '../../lib/api/resources'
import * as bridge from '../../lib/desktopBridge'
import { HostedAddOnRow } from './HostedAddOnRow'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  startHostedOAuth: vi.fn(),
  exchangeHostedOAuth: vi.fn(),
  probeHostedStatus: vi.fn()
}))

const HOSTED: IntegrationHosted = {
  server: 'onshape_fs',
  display_name: 'FeatureScript',
  notice: 'It runs as you, using your own Onshape sign-in.',
  subscribe_url: 'https://cad.onshape.com/appstore/apps/Onshape%20Labs/abc'
}

function source(config: Record<string, unknown>): Source {
  return {
    id: 's1',
    project_id: 'p1',
    type: 'onshape',
    name: 'strider-cad',
    status: 'connected',
    config,
    account_login: null,
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: ''
  }
}

const props = (
  config: Record<string, unknown>,
  onChanged = vi.fn()
): Parameters<typeof HostedAddOnRow>[0] => ({
  source: source(config),
  projectId: 'p1',
  hosted: HOSTED,
  providerName: 'Onshape',
  onChanged
})

beforeEach(() => vi.clearAllMocks())

describe('state comes from the server, never from this component', () => {
  it('does not offer a second enable action for an account-owned grant', () => {
    const input = props({})
    input.source.connection_id = 'c1'
    render(<HostedAddOnRow {...input} />)
    expect(screen.queryByRole('button', { name: 'Enable FeatureScript' })).not.toBeInTheDocument()
    expect(screen.getByText(/linked account/)).toBeInTheDocument()
  })
  it('an absent config reads as not connected, never as optimistically ready', () => {
    render(<HostedAddOnRow {...props({})} />)
    expect(screen.getByRole('button', { name: 'Enable FeatureScript' })).toBeInTheDocument()
  })

  it('a malformed config also reads as not connected', () => {
    render(<HostedAddOnRow {...props({ hosted: 'nonsense' })} />)
    expect(screen.getByRole('button', { name: 'Enable FeatureScript' })).toBeInTheDocument()
  })

  it('shows the connect disclosure verbatim before anything is enabled', () => {
    render(<HostedAddOnRow {...props({})} />)
    expect(screen.getByText(/It runs as you, using your own Onshape sign-in\./)).toBeInTheDocument()
  })

  it('reports ready without offering a disable button', () => {
    // Removal happens in the vendor's App Store — the disclosure says so, and
    // offering a "disable" here would imply Solus can unsubscribe them.
    render(<HostedAddOnRow {...props({ hosted: { onshape_fs: { state: 'ready' } } })} />)
    expect(screen.getByText('FEATURESCRIPT ON')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('when a subscription is needed', () => {
  const NEEDS = {
    hosted: {
      onshape_fs: { state: 'subscription_required', detail: 'No FeatureScript subscription.' }
    }
  }

  it("shows the vendor's own reason plus BOTH remedies", () => {
    // One capability probe cannot separate "not subscribed" from "your admin
    // has not permitted Onshape Labs", so the copy names both rather than
    // asserting a cause we cannot actually distinguish.
    render(<HostedAddOnRow {...props(NEEDS)} />)
    expect(screen.getByText(/No FeatureScript subscription\./)).toBeInTheDocument()
    expect(screen.getByText(/administrator may have to permit it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Onshape App Store' })).toBeInTheDocument()
  })

  it('opens the store through the sender-gated bridge, not window.open', async () => {
    const openStore = vi.fn().mockResolvedValue({ ok: true })
    vi.spyOn(bridge, 'getDesktopHostedBridge').mockReturnValue({ openStore })
    render(<HostedAddOnRow {...props(NEEDS)} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open Onshape App Store' }))
    })
    expect(openStore).toHaveBeenCalledWith(HOSTED.subscribe_url)
  })

  it('re-checks by asking the backend to probe, and refreshes on success', async () => {
    const onChanged = vi.fn()
    vi.mocked(resources.probeHostedStatus).mockResolvedValue({
      server: 'onshape_fs',
      state: 'ready',
      tool_count: 12
    })
    render(<HostedAddOnRow {...props(NEEDS, onChanged)} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check again/ }))
    })
    expect(resources.probeHostedStatus).toHaveBeenCalledWith('p1', 's1', 'onshape_fs')
    expect(onChanged).toHaveBeenCalled()
  })
})

describe('enabling', () => {
  it('runs the second browser trip and exchanges the code server-side', async () => {
    const onChanged = vi.fn()
    const awaitOAuth = vi.fn().mockResolvedValue({ code: 'auth-code' })
    vi.spyOn(bridge, 'getDesktopOAuthBridge').mockReturnValue({
      getRedirectUrl: vi.fn(),
      awaitGithub: vi.fn(),
      getConnectorRedirectUrl: vi.fn(),
      awaitOAuth
    })
    vi.mocked(resources.startHostedOAuth).mockResolvedValue({
      authorize_url: 'https://fs-mcp.labs.onshape.app/authorize?x=1',
      state: 'st',
      redirect_uri: 'http://localhost:53682/auth/callback'
    })
    vi.mocked(resources.exchangeHostedOAuth).mockResolvedValue({
      server: 'onshape_fs',
      state: 'ready',
      tool_count: 12
    })

    render(<HostedAddOnRow {...props({}, onChanged)} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enable FeatureScript' }))
    })

    expect(awaitOAuth).toHaveBeenCalledWith('https://fs-mcp.labs.onshape.app/authorize?x=1', 'st')
    // The CODE is never exchanged in the renderer — it goes back to the API,
    // which holds the PKCE verifier and checks the state belongs to this user.
    expect(resources.exchangeHostedOAuth).toHaveBeenCalledWith('p1', 's1', 'onshape_fs', {
      state: 'st',
      code: 'auth-code'
    })
    expect(onChanged).toHaveBeenCalled()
  })

  it('surfaces the single-flight loopback refusal verbatim', async () => {
    // The capture is single-flight: a connect already running in the wizard
    // makes this resolve before any browser opens. The message is already
    // honest and already actionable, so it is shown as-is.
    vi.spyOn(bridge, 'getDesktopOAuthBridge').mockReturnValue({
      getRedirectUrl: vi.fn(),
      awaitGithub: vi.fn(),
      getConnectorRedirectUrl: vi.fn(),
      awaitOAuth: vi.fn().mockResolvedValue({ error: 'A sign-in is already in progress.' })
    })
    vi.mocked(resources.startHostedOAuth).mockResolvedValue({
      authorize_url: 'https://fs-mcp.labs.onshape.app/authorize',
      state: 'st',
      redirect_uri: 'http://localhost:53682/auth/callback'
    })

    render(<HostedAddOnRow {...props({})} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enable FeatureScript' }))
    })
    expect(screen.getByText('A sign-in is already in progress.')).toBeInTheDocument()
    expect(resources.exchangeHostedOAuth).not.toHaveBeenCalled()
  })

  it('says so honestly when there is no desktop bridge', async () => {
    vi.spyOn(bridge, 'getDesktopOAuthBridge').mockReturnValue(null)
    render(<HostedAddOnRow {...props({})} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enable FeatureScript' }))
    })
    expect(screen.getByText(/needs the desktop app/)).toBeInTheDocument()
    expect(resources.startHostedOAuth).not.toHaveBeenCalled()
  })
})
