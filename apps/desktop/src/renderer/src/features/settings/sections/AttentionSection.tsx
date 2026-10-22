// Settings › Needs attention (SOLUSDEV-318): the top of the page holds every
// task the user must act on, each as an action card with the buttons that do
// it — the fix for "the Screen Recording URL rendered as plain text". Items
// come from attention.ts; this file only renders them.
import { Button } from '../../../components/ui/Button'
import { Callout, CodeLine } from '../settingsUi'
import { ATTENTION_ANCHOR } from '../settingsSections.constants'
import { RevealList } from '../Reveal'
import type { AttentionItem } from '../attention'

export interface AttentionActions {
  openCaptureSettings: () => void
  recheckCapture: () => void
  turnOffCapture: () => void
  openBilling: () => void
  openAccounts: () => void
}

const SCREEN_RECORDING_PATH = 'System Settings › Privacy & Security › Screen Recording › Solus'

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function CaptureCard({
  item,
  actions
}: {
  item: Extract<AttentionItem, { kind: 'capture' }>
  actions: AttentionActions
}): React.JSX.Element {
  return (
    <Callout
      tone="warn"
      title="SOL can't see your screen yet"
      actions={
        <>
          {item.canOpenSettings && (
            <Button kind="primary" size="sm" onClick={actions.openCaptureSettings}>
              Open Screen Recording settings
            </Button>
          )}
          <Button kind="ghost" size="sm" onClick={actions.recheckCapture}>
            Recheck
          </Button>
          <Button kind="bare" size="sm" onClick={actions.turnOffCapture}>
            Turn off screen capture
          </Button>
        </>
      }
    >
      <div>{item.message}</div>
      {item.canOpenSettings && (
        <div style={{ marginTop: 8 }}>
          <CodeLine>{SCREEN_RECORDING_PATH}</CodeLine>
        </div>
      )}
    </Callout>
  )
}

function AttentionCard({
  item,
  actions
}: {
  item: AttentionItem
  actions: AttentionActions
}): React.JSX.Element {
  switch (item.kind) {
    case 'capture':
      return <CaptureCard item={item} actions={actions} />
    case 'trial':
      return (
        <Callout
          tone="acc"
          title={
            item.ended
              ? 'Your trial has ended'
              : `Your trial ends in ${item.days} ${item.days === 1 ? 'day' : 'days'}`
          }
          actions={
            <Button kind="soft" size="sm" onClick={actions.openBilling}>
              Choose a plan
            </Button>
          }
        >
          Pick a plan to keep your projects and credits. Nothing is deleted when the trial ends.
        </Callout>
      )
    case 'reconnect':
      return (
        <Callout
          tone="warn"
          title={`Reconnect ${capitalize(item.provider)}${item.login ? ` (@${item.login})` : ''}`}
          actions={
            <Button kind="soft" size="sm" onClick={actions.openAccounts}>
              Reconnect
            </Button>
          }
        >
          Its sign-in expired, so syncs from this account are paused until you sign in again.
        </Callout>
      )
  }
}

export function AttentionSection({
  items,
  actions
}: {
  items: readonly AttentionItem[]
  actions: AttentionActions
}): React.JSX.Element | null {
  // Cards expand in when a problem appears (e.g. turning on "SOL sees your
  // screen" without the permission) and collapse out once it is fixed.
  return (
    <RevealList
      id={ATTENTION_ANCHOR}
      label="Needs attention"
      items={items}
      keyOf={attentionKey}
      renderItem={(item) => <AttentionCard item={item} actions={actions} />}
    />
  )
}

function attentionKey(item: AttentionItem): string {
  return item.kind === 'reconnect' ? `reconnect:${item.connectionId}` : item.kind
}
