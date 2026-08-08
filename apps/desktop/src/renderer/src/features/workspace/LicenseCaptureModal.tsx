// BYO-license capture modal (SOLUSDEV-102 / MCP-05): one masked input per
// license_secrets key NAME for a byo_paid server. Secret values live ONLY in
// this component's local state — never in a Zustand store, never logged —
// and flow renderer → preload → main → companion stdin via
// solus.bridge.submitLicense. The ack surface is by key NAME only; the
// license_state on the bridge pill flips to ready once the cloud stores it.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { ModalShell, MODAL_INPUT_STYLE } from './modals'

/** Client-side mirror of MCP_SERVER_CATALOG's `license_secrets` key NAMES
 *  (packages/api/src/solus_api/agent/tools/mcp_servers.py) — the bridge
 *  status endpoint sends `license_state` but not the key names. NAMES only;
 *  never values. Keep in sync when the catalog gains byo_paid servers. */
const LICENSE_SECRET_KEYS: Readonly<Record<string, readonly string[]>> = {
  altium: ['altium_license'],
  solidworks: ['solidworks_serial'],
  autocad: ['autocad_license']
}

interface SubmitResult {
  ok: boolean
  error?: string
}

/** Per-input character cap (M4). A single license secret is short; the
 *  companion drops any stdin control line over its 16 KiB cap, so bound each
 *  field well under that at the point of entry. */
const LICENSE_INPUT_MAX_LENGTH = 4096

/** Local accessor for preload's `solus.bridge.submitLicense` (the shared
 *  desktopBridge helper predates this channel and is outside this change's
 *  file set). Null outside the Electron desktop app. */
function getSubmitLicense():
  | ((server: string, secrets: Record<string, string>) => Promise<SubmitResult>)
  | null {
  const w = window as unknown as {
    solus?: {
      bridge?: { submitLicense?: (s: string, x: Record<string, string>) => Promise<SubmitResult> }
    }
  }
  return w.solus?.bridge?.submitLicense ?? null
}

function CaptureForm({
  keys,
  values,
  error,
  onChange,
  onSubmit
}: {
  keys: readonly string[]
  values: Record<string, string>
  error: string | null
  onChange: (key: string, value: string) => void
  onSubmit: () => void
}): React.JSX.Element {
  return (
    <>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
        Your license is sent to your local companion and stored for your team. It is never shown
        again here.
      </div>
      {keys.map((key) => (
        <input
          key={key}
          type="password"
          aria-label={key}
          placeholder={key}
          autoComplete="off"
          value={values[key] ?? ''}
          maxLength={LICENSE_INPUT_MAX_LENGTH}
          onChange={(e) => onChange(key, e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
          style={{ ...MODAL_INPUT_STYLE, fontFamily: 'var(--font-mono)' }}
        />
      ))}
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
    </>
  )
}

function ModalNote({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 8, lineHeight: 1.5 }}>
      {children}
    </div>
  )
}

export function LicenseCaptureModal({
  server,
  onClose
}: {
  server: string
  onClose: () => void
}): React.JSX.Element {
  const keys = LICENSE_SECRET_KEYS[server] ?? []
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const mode = keys.length === 0 ? 'unknown' : submitted ? 'submitted' : 'form'

  const close = (): void => {
    setValues({}) // inputs cleared on close — values never outlive the modal
    onClose()
  }

  const submit = async (): Promise<void> => {
    if (keys.some((key) => !values[key]?.trim())) return
    const submitLicense = getSubmitLicense()
    if (!submitLicense) {
      setError('License capture needs the Solus desktop app with the local companion.')
      return
    }
    setBusy(true)
    setError(null)
    const secrets = Object.fromEntries(keys.map((key) => [key, values[key].trim()]))
    const result = await submitLicense(server, secrets).catch(() => ({ ok: false }) as SubmitResult)
    setBusy(false)
    if (!result.ok) {
      setError(result.error ?? 'Something went wrong. Please try again.')
      return
    }
    setValues({}) // relayed — drop the values immediately
    setSubmitted(true)
  }

  return (
    <ModalShell onClose={close}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Add {server} license</div>
      {mode === 'unknown' && (
        <ModalNote>
          This app version doesn&apos;t know the license key names for {server}. Update Solus and
          try again.
        </ModalNote>
      )}
      {mode === 'form' && (
        <CaptureForm
          keys={keys}
          values={values}
          error={error}
          onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))}
          onSubmit={() => void submit()}
        />
      )}
      {mode === 'submitted' && (
        <ModalNote>
          License submitted ({keys.join(', ')}). The bridge shows this server as ready once your
          companion relays it.
        </ModalNote>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={close}>
          {mode === 'form' ? 'Cancel' : 'Close'}
        </Button>
        {mode === 'form' && (
          <Button kind="primary" size="sm" onClick={() => void submit()}>
            {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Add license'}
          </Button>
        )}
      </div>
    </ModalShell>
  )
}
