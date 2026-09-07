// The Open-in button set (SOLUSDEV-249 / I2): one button per tool a detected
// project can open in, built from the API's `open_targets` — never guessed.
// Shared by the LOCAL FOLDER card's rows and the graph inspector. A launch is
// the user's own click, dispatched through the API to the companion; the
// tool's refusal (`launched: false`) is shown here, verbatim.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { LocalOpenTool, OpenLocalFolderResult } from '../../lib/api/resources.localfolder'
import { OPEN_LABEL } from './localFolder.constants'

export interface OpenInButtonsProps {
  targets: readonly LocalOpenTool[]
  /** Non-null disables every button and says why (bridge offline, no source). */
  disabledReason?: string | null
  onOpen: (tool: LocalOpenTool) => Promise<OpenLocalFolderResult | null>
}

export function OpenInButtons({
  targets,
  disabledReason = null,
  onOpen
}: OpenInButtonsProps): React.JSX.Element | null {
  const [busy, setBusy] = useState<LocalOpenTool | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  if (targets.length === 0) return null

  const launch = async (tool: LocalOpenTool): Promise<void> => {
    setBusy(tool)
    setReason(null)
    const answer = await onOpen(tool)
    setBusy(null)
    if (answer && !answer.launched) setReason(answer.reason ?? `${OPEN_LABEL[tool]} did not launch`)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
      <div data-testid="open-in-group" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {targets.map((tool) => (
          <Button
            key={tool}
            kind="ghost"
            size="sm"
            disabled={disabledReason !== null || busy !== null}
            title={disabledReason ?? undefined}
            onClick={() => void launch(tool)}
          >
            {OPEN_LABEL[tool]}
          </Button>
        ))}
      </div>
      {reason && (
        <div role="note" style={{ fontSize: 10.5, color: 'var(--warn)', lineHeight: 1.45 }}>
          {reason}
        </div>
      )}
    </div>
  )
}
