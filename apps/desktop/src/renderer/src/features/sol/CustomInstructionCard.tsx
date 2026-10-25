// CUSTOM INSTRUCTIONS (design template, SOL page right column): the person's standing
// instruction. It is the per-ACCOUNT setting (`sol_custom_instruction`) — there is no
// per-chat instruction — and the card says so, so nobody expects one chat to differ.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { useCustomInstruction } from './useCustomInstruction'

const INSTRUCTION_CAP = 500

const INSTRUCTION_TEXTAREA_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  padding: '8px 10px',
  fontSize: 12,
  lineHeight: 1.5,
  fontFamily: 'var(--font-ui)',
  resize: 'vertical',
  outline: 'none'
}

export function CustomInstructionCard(): React.JSX.Element {
  const { instruction, status, save } = useCustomInstruction()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState(false)

  const beginEdit = (): void => {
    setDraft(instruction ?? '')
    setFailed(false)
    setEditing(true)
  }
  const submit = async (): Promise<void> => {
    const ok = await save(draft)
    setFailed(!ok)
    if (ok) setEditing(false)
  }

  return (
    <section className="sol-panel-in" aria-label="Custom instructions">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono size={10} ls="0.08em">
          CUSTOM INSTRUCTIONS
        </Mono>
        {status === 'ready' && !editing && (
          <Button kind="bare" size="sm" onClick={beginEdit}>
            {instruction ? 'Edit' : 'Add'}
          </Button>
        )}
      </div>
      <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 4 }}>
        Applies to every chat on this account.
      </div>
      {!editing && (
        <div
          style={{
            fontSize: 12,
            color: instruction ? 'var(--tx)' : 'var(--mut)',
            marginTop: 8,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap'
          }}
        >
          {status === 'offline'
            ? 'Unavailable offline.'
            : (instruction ?? 'None set. SOL follows your saved preferences here.')}
        </div>
      )}
      {editing && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={INSTRUCTION_CAP}
            rows={4}
            aria-label="Custom instruction"
            placeholder="Prefer metric units. Flag servo commands past URDF limits."
            style={INSTRUCTION_TEXTAREA_STYLE}
          />
          {failed && (
            <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 4 }}>
              Couldn&apos;t save — try again.
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 6 }}>
            <Button kind="ghost" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button kind="primary" size="sm" onClick={() => void submit()}>
              Save
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
