// Connect action for a local-bridge catalog tile (SOLUSDEV-72). There is no
// credential flow to run: the tool connects when its vendor app runs its MCP
// server and the Solus companion bridges it. This modal states exactly that,
// with the registry's own guidance — nothing invented, nothing implied.
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import type { LocalTool } from '../../../lib/api/resources'
import { ModalShell } from '../../workspace/modals'

export function LocalBridgeConnectModal({
  tool,
  onClose
}: {
  tool: LocalTool
  onClose: () => void
}): React.JSX.Element {
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Connect {tool.display_name}</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        {tool.display_name} runs its own local server; the Solus companion bridges it — no account
        to link. Its status appears under Local Connections on the Sources page.
      </div>
      <div style={{ fontSize: 12.5, marginTop: 10, lineHeight: 1.55 }}>{tool.connect_notice}</div>
      <div style={{ marginTop: 10 }}>
        <Mono size={9.5} color="var(--mut)">
          {tool.url_host}
        </Mono>
      </div>
      <div style={{ display: 'flex', marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="primary" size="sm" onClick={onClose}>
          Got it
        </Button>
      </div>
    </ModalShell>
  )
}
