// Solus — cross-domain alert detail screen ("the magic moment"), ported
// pixel-faithfully from TestDesign/app/alert.jsx. Alert resolution lives in
// the shell store; the why-explanation defaults to the user's SOL mode
// (ADR-016) and stays switchable inline.
import { useMemo, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Avatar } from '../../components/ui/Avatar'
import { Spinner } from '../../components/ui/Spinner'
import { Segmented } from '../../components/ui/Segmented'
import { Icons } from '../../components/ui/icons.constants'
import { SOLUS_DOMAINS, dcol, type DomainId } from '../../theme/tokens.constants'
import { ALERTS } from '../workspace/workspaceData.constants'
import type { Alert } from '../workspace/workspaceData.constants'
import { alertsWithState, useShellStore } from '../workspace/shellStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { SevBadge, CodeBlock, DiffBlock, BeforeAfter } from './alertBlocks'

const APPLY_STEPS: readonly string[] = [
  'Creating branch fix/u4-pin-map…',
  'Applying patch to motor_driver.c…',
  'Running firmware build check…',
  'Opening PR #144 in strider-fw…'
]

const APPLY_STEP_MS = 850
const APPLY_DONE_EXTRA_MS = 500

const WHY_MODES: readonly SolMode[] = ['Guide', 'Expert']

const TRACE: readonly (readonly [DomainId, string, string])[] = [
  ['ee', 'strider_main.sch rev 42', 'change detected'],
  ['ee', 'U4 · DRV8316C', 'interface contract diff'],
  ['sw', 'motor_driver.c +2 files', 'stale references found'],
  ['rt', 'FL knee phase', 'predicted: ripple / shoot-through']
]

type ApplyState = 'idle' | 'busy' | 'done'

interface BackLinkProps {
  onBack: () => void
}

function BackLink({ onBack }: BackLinkProps): React.JSX.Element {
  return (
    <span
      onClick={onBack}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        fontSize: 12.5,
        color: 'var(--mut)',
        cursor: 'pointer'
      }}
    >
      <Icons.arrowL size={13} /> Back
    </span>
  )
}

interface AlertHeaderProps {
  alert: Alert
  resolved: boolean
  onAskSol: (key: string) => void
}

function AlertHeader({ alert, resolved, onAskSol }: AlertHeaderProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 18,
        marginTop: 14
      }}
    >
      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <SevBadge sev={alert.sev} state={resolved ? 'resolved' : 'open'} />
          <Mono size={9.5}>
            <span style={{ color: dcol(alert.fromD) }}>{SOLUS_DOMAINS[alert.fromD].label}</span>
            <span style={{ color: 'var(--mut)' }}> → </span>
            <span style={{ color: dcol(alert.toD) }}>{SOLUS_DOMAINS[alert.toD].label}</span>
          </Mono>
        </div>
        <h1
          style={{
            margin: '12px 0 0',
            fontSize: 26,
            fontWeight: 600,
            letterSpacing: '-0.02em',
            lineHeight: 1.2
          }}
        >
          {alert.title}
        </h1>
        <div
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'center',
            marginTop: 10,
            fontSize: 12.5,
            color: 'var(--mut)'
          }}
        >
          <Avatar name={alert.actor} size={20} /> {alert.actor} · {alert.time} · detected by SOL in
          90 ms
        </div>
      </div>
      <Button kind="ghost" size="sm" onClick={() => onAskSol('alertq')}>
        <Icons.sol size={13} /> Ask SOL about this
      </Button>
    </div>
  )
}

interface ResolvedBannerProps {
  alert: Alert
  wasResolvedAtMount: boolean
}

function ResolvedBanner({ alert, wasResolvedAtMount }: ResolvedBannerProps): React.JSX.Element {
  return (
    <div
      style={{
        marginTop: 18,
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        background: 'color-mix(in srgb, var(--ok) 8%, transparent)',
        border: '1px solid color-mix(in srgb, var(--ok) 40%, transparent)',
        borderRadius: 3,
        padding: '11px 14px'
      }}
    >
      <span style={{ color: 'var(--ok)' }}>
        <Icons.check size={15} />
      </span>
      <span style={{ fontSize: 12.5 }}>
        {wasResolvedAtMount ? (
          <>
            Resolved {alert.time} by {alert.resolvedBy ?? 'Marcus Hale'} — fix merged in{' '}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>
              {alert.issue.repo}#{alert.issue.num}
            </span>
          </>
        ) : (
          <>
            Fix applied — PR{' '}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>strider-fw#144</span>{' '}
            opened and assigned to you. SOL will re-check on merge.
          </>
        )}
      </span>
    </div>
  )
}

function ChangeCard({ alert }: { alert: Alert }): React.JSX.Element {
  return (
    <Card pad={18}>
      <Mono size={9.5}>WHAT CHANGED</Mono>
      <div style={{ fontSize: 14.5, fontWeight: 600, marginTop: 8 }}>{alert.change.title}</div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--mut)',
          marginTop: 3
        }}
      >
        {alert.change.source}
      </div>
      <div style={{ marginTop: 16 }}>
        <BeforeAfter change={alert.change} />
      </div>
      <div style={{ marginTop: 14, fontSize: 11.5, color: 'var(--mut)', fontStyle: 'italic' }}>
        {alert.change.commit}
      </div>
    </Card>
  )
}

function FilesCard({ alert }: { alert: Alert }): React.JSX.Element {
  return (
    <Card pad={18}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono size={9.5}>
          AFFECTED CODE · {alert.files.length} FILE{alert.files.length > 1 ? 'S' : ''}
        </Mono>
        <Mono size={9} color={dcol('sw')}>
          ● SOFTWARE
        </Mono>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 14 }}>
        {alert.files.map((f) => (
          <div key={f.path}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 6,
                gap: 10
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  color: 'var(--tx)',
                  display: 'inline-flex',
                  gap: 7,
                  alignItems: 'center'
                }}
              >
                <Icons.file size={12} /> {f.path}{' '}
                <span style={{ color: 'var(--mut)' }}>{f.range}</span>
              </span>
              <span style={{ fontSize: 11, color: 'var(--warn)' }}>{f.note}</span>
            </div>
            <CodeBlock lines={f.code} hot={f.hot} />
          </div>
        ))}
      </div>
    </Card>
  )
}

interface WhyCardProps {
  alert: Alert
  whyMode: SolMode
  onWhyMode: (mode: SolMode) => void
}

function WhyCard({ alert, whyMode, onWhyMode }: WhyCardProps): React.JSX.Element {
  return (
    <Card pad={18}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono size={9.5}>WHY IT BREAKS</Mono>
        <Segmented size="sm" options={WHY_MODES} value={whyMode} onChange={onWhyMode} />
      </div>
      <p
        style={{
          fontSize: whyMode === 'Guide' ? 12.5 : 12,
          lineHeight: 1.65,
          color: 'var(--tx)',
          margin: '12px 0 0',
          fontFamily: whyMode === 'Expert' ? 'var(--font-mono)' : 'var(--font-ui)'
        }}
      >
        {whyMode === 'Guide' ? alert.why.guide : alert.why.expert}
      </p>
    </Card>
  )
}

function ApplyProgress({ step }: { step: number }): React.JSX.Element {
  return (
    <div style={{ marginTop: 14, fontFamily: 'var(--font-mono)', fontSize: 10.5 }}>
      {APPLY_STEPS.map((s, i) => (
        <div
          key={s}
          style={{
            display: 'flex',
            gap: 9,
            alignItems: 'center',
            padding: '4px 0',
            color: i < step ? 'var(--ok)' : i === step ? 'var(--acc)' : 'var(--mut)',
            opacity: i > step ? 0.45 : 1
          }}
        >
          {i < step ? (
            <span>✓</span>
          ) : i === step ? (
            <Spinner size={10} />
          ) : (
            <span style={{ width: 10 }} />
          )}
          {s}
        </div>
      ))}
    </div>
  )
}

interface FixCardProps {
  alert: Alert
  applyState: ApplyState
  applyStep: number
  issueDone: boolean
  wasResolvedAtMount: boolean
  onApply: () => void
  onCreateIssue: () => void
}

function FixCard({
  alert,
  applyState,
  applyStep,
  issueDone,
  wasResolvedAtMount,
  onApply,
  onCreateIssue
}: FixCardProps): React.JSX.Element {
  const resolved = applyState === 'done'
  return (
    <Card
      pad={18}
      style={{
        borderColor: resolved ? 'var(--bd)' : 'color-mix(in srgb, var(--acc) 45%, var(--bd))'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono size={9.5} color="var(--acc)">
          SUGGESTED FIX
        </Mono>
        <Mono size={9}>{Math.round(alert.fix.confidence * 100)}% CONFIDENCE</Mono>
      </div>
      <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 10 }}>{alert.fix.summary}</div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--mut)',
          margin: '12px 0 6px'
        }}
      >
        {alert.fix.file}
      </div>
      <DiffBlock lines={alert.fix.diff} />

      {applyState === 'idle' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <Button id="btn-apply-fix" kind="primary" style={{ flex: 1 }} onClick={onApply}>
            Apply fix
          </Button>
          <Button kind="ghost" style={{ flex: 1 }} onClick={onCreateIssue} disabled={issueDone}>
            {issueDone ? (
              <>
                <span style={{ color: 'var(--ok)' }}>
                  <Icons.check size={13} />
                </span>{' '}
                #144 created
              </>
            ) : (
              'Create issue'
            )}
          </Button>
        </div>
      )}
      {applyState === 'busy' && <ApplyProgress step={applyStep} />}
      {applyState === 'done' && !wasResolvedAtMount && (
        <div
          style={{
            marginTop: 14,
            display: 'flex',
            gap: 9,
            alignItems: 'center',
            fontSize: 12,
            color: 'var(--ok)'
          }}
        >
          <Icons.check size={14} /> Patch applied — PR strider-fw#144 awaiting review
        </div>
      )}
    </Card>
  )
}

function TraceCard(): React.JSX.Element {
  return (
    <Card pad={14}>
      <Mono size={9.5}>TRACE</Mono>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, marginTop: 10 }}>
        {TRACE.map(([d, l, n], i) => (
          <div key={l} style={{ display: 'flex', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 99,
                  background: dcol(d),
                  marginTop: 4,
                  flexShrink: 0
                }}
              />
              {i < TRACE.length - 1 && (
                <span style={{ width: 1, flex: 1, background: 'var(--bd)', minHeight: 18 }} />
              )}
            </div>
            <div style={{ paddingBottom: i < TRACE.length - 1 ? 10 : 0 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--tx)' }}>
                {l}
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{n}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function AlertNotFound({ onBack }: { onBack: () => void }): React.JSX.Element {
  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 1060, margin: '0 auto', padding: '22px 28px 48px' }}>
        <BackLink onBack={onBack} />
        <div style={{ marginTop: 18, fontSize: 13, color: 'var(--mut)' }}>Alert not found.</div>
      </div>
    </div>
  )
}

interface AlertDetailProps {
  alert: Alert
  onBack: () => void
  onAskSol: (key: string) => void
}

function AlertDetail({ alert, onBack, onAskSol }: AlertDetailProps): React.JSX.Element {
  const resolveAlert = useShellStore((s) => s.resolveAlert)
  const setToast = useShellStore((s) => s.setToast)
  const solMode = useSettingsStore((s) => s.solMode)
  const wasResolvedAtMount = useRef(alert.state === 'resolved').current
  const [applyState, setApplyState] = useState<ApplyState>(wasResolvedAtMount ? 'done' : 'idle')
  const [applyStep, setApplyStep] = useState(0)
  const [issueDone, setIssueDone] = useState(false)
  const [whyMode, setWhyMode] = useState<SolMode>(solMode)

  const apply = (): void => {
    setApplyState('busy')
    APPLY_STEPS.forEach((_, i) => {
      if (i > 0) setTimeout(() => setApplyStep(i), i * APPLY_STEP_MS)
    })
    setTimeout(
      () => {
        setApplyState('done')
        resolveAlert(alert.id)
      },
      APPLY_STEPS.length * APPLY_STEP_MS + APPLY_DONE_EXTRA_MS
    )
  }
  const createIssue = (): void => {
    setIssueDone(true)
    setToast({
      kind: 'ok',
      title: `Issue #144 created in ${alert.issue.repo}`,
      body: 'Linked to this alert with the full cross-domain trace attached.'
    })
  }
  const resolved = applyState === 'done'

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 1060, margin: '0 auto', padding: '22px 28px 48px' }}>
        <BackLink onBack={onBack} />
        <AlertHeader alert={alert} resolved={resolved} onAskSol={onAskSol} />
        {resolved && <ResolvedBanner alert={alert} wasResolvedAtMount={wasResolvedAtMount} />}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0,1fr) 360px',
            gap: 18,
            marginTop: 22,
            alignItems: 'start'
          }}
        >
          {/* left: what changed + impact */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
            <ChangeCard alert={alert} />
            <FilesCard alert={alert} />
          </div>

          {/* right: why + fix */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <WhyCard alert={alert} whyMode={whyMode} onWhyMode={setWhyMode} />
            <FixCard
              alert={alert}
              applyState={applyState}
              applyStep={applyStep}
              issueDone={issueDone}
              wasResolvedAtMount={wasResolvedAtMount}
              onApply={apply}
              onCreateIssue={createIssue}
            />
            <TraceCard />
          </div>
        </div>
      </div>
    </div>
  )
}

interface AlertScreenProps {
  alertId: string
  onBack: () => void
  onAskSol: (key: string) => void
}

export function AlertScreen({ alertId, onBack, onAskSol }: AlertScreenProps): React.JSX.Element {
  const resolved = useShellStore((s) => s.resolved)
  const alert = useMemo(
    () => alertsWithState(ALERTS, resolved).find((a) => a.id === alertId),
    [resolved, alertId]
  )
  if (!alert) return <AlertNotFound onBack={onBack} />
  return <AlertDetail key={alert.id} alert={alert} onBack={onBack} onAskSol={onAskSol} />
}
