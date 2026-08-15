// SOLX-03: what the overlay window actually paints — a pointer at one real
// control, or nothing.
//
// M7 (SOL-IPC-01): `title` and `instruction` are UNTRUSTED. They can originate in
// a vendored fork's knowledge base, they have crossed a process boundary and a
// wire to get here, and they are rendered on top of the user's real application.
// They are therefore placed as React children — text nodes — and this file
// contains no `dangerouslySetInnerHTML`, no innerHTML, and no string-built
// markup. A red-team fixture in the sibling test asserts that, not just a
// comment.
//
// Positioning uses PERCENTAGES from the normalised 0..1 locator rather than
// pixels, so the pointer stays on the control if the tool window is resized
// before the next `reposition` arrives.
import type { OverlayView } from './overlaySession'

const PANEL_STYLE: React.CSSProperties = {
  position: 'absolute',
  left: 16,
  bottom: 16,
  maxWidth: 420,
  // Bounded because the text is untrusted: CTR-06 caps a string at 2000
  // characters, and 2000 characters unbounded would grow this panel up the
  // screen and blanket the tool the user is trying to see.
  maxHeight: '30vh',
  overflow: 'hidden',
  padding: '10px 12px',
  borderRadius: 8,
  background: 'rgba(12, 12, 14, 0.86)',
  color: '#f4f4f5',
  font: '13px/1.5 var(--font-sans, system-ui, sans-serif)',
  pointerEvents: 'none' // the window is click-through; never intercept a click
}

const POINTER_STYLE: React.CSSProperties = {
  position: 'absolute',
  border: '2px solid var(--acc, #7dd3fc)',
  borderRadius: 6,
  boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.18)', // dim everything but the target
  pointerEvents: 'none'
}

export function GuideOverlay({ view }: { view: OverlayView | null }): React.JSX.Element | null {
  if (view === null) return null
  const pointing = view.decision.kind === 'annotate' ? view.decision.box : null
  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden' }}>
      {pointing && (
        <div
          data-testid="overlay-pointer"
          style={{
            ...POINTER_STYLE,
            left: `${pointing.x * 100}%`,
            top: `${pointing.y * 100}%`,
            width: `${pointing.w * 100}%`,
            height: `${pointing.h * 100}%`
          }}
        />
      )}
      {/* `status`, not `alert`: this narrates a step the user is working through,
          and an assertive live region would interrupt their screen reader mid-task. */}
      <div role="status" style={PANEL_STYLE}>
        <div style={{ opacity: 0.7, fontSize: 11 }}>
          Step {view.index + 1} of {view.total}
        </div>
        <strong>{view.title}</strong>
        <div>{view.instruction}</div>
      </div>
    </div>
  )
}
