// The Code environment details dialog (SOLUSDEV-250 / I3): what the live probe
// found on this machine, what the graph holds for the linked folder, the
// conflicts the checker flagged and the environment split SOL proposes. The
// footer hands the setup to SOL — nothing here runs anything; every install,
// run and test goes through SOL's approval card.
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import type { CodeEnvironmentView } from '../../lib/api/resources.codeenv'
import {
  ConflictsSection,
  InterpreterSection,
  ProposalSection,
  RequirementsSection,
  Section,
  VenvSection
} from './CodeEnvironmentSections'
import { ModalShell } from './modals'
import './codeEnvironment.css'

export interface CodeEnvironmentModalProps {
  view: CodeEnvironmentView
  onClose: () => void
  /** "Ask SOL to set it up" — the row decides how the hand-off happens. */
  onAskSol: () => void
}

function CloseButton({ onClose }: { onClose: () => void }): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label="Close"
      className="interactive"
      onClick={onClose}
      style={{
        background: 'transparent',
        border: 'none',
        color: 'var(--mut)',
        cursor: 'pointer',
        padding: 4,
        display: 'inline-flex'
      }}
    >
      <Icons.x size={13} />
    </button>
  )
}

export function CodeEnvironmentModal({
  view,
  onClose,
  onAskSol
}: CodeEnvironmentModalProps): React.JSX.Element {
  const canAskSol = view.requirements.count > 0 && view.proposal !== null
  return (
    <ModalShell onClose={onClose} width={560}>
      <div role="dialog" aria-label="Code environment">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Mono size={9.5}>CODE ENVIRONMENT</Mono>
          <CloseButton onClose={onClose} />
        </div>
        <div style={{ maxHeight: '62vh', overflowY: 'auto' }}>
          <Section title="Interpreter" index={0}>
            <InterpreterSection probe={view.probe} />
          </Section>
          <Section title="Virtual environment" index={1}>
            <VenvSection probe={view.probe} />
          </Section>
          <Section title="Requirements" index={2}>
            <RequirementsSection requirements={view.requirements} />
          </Section>
          <Section title="Conflicts" index={3}>
            <ConflictsSection conflicts={view.conflicts} />
          </Section>
          <Section title="Proposal" index={4}>
            <ProposalSection proposal={view.proposal} requirementCount={view.requirements.count} />
          </Section>
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
            marginTop: 18,
            paddingTop: 14,
            borderTop: '1px solid var(--bd)'
          }}
        >
          <Button kind="primary" size="sm" disabled={!canAskSol} onClick={onAskSol}>
            Ask SOL to set it up
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}
