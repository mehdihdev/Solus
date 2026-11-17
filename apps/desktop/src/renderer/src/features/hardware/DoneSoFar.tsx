// SOLUSDEV-326 P3: the "Done so far" row under the card slot. Always 30 px, so nothing below it
// moves when the first receipt lands. Receipts are tool-authored text and print as text.
export function DoneSoFar({ receipts }: { receipts: readonly string[] }): React.JSX.Element {
  return (
    <p
      data-testid="done-so-far"
      style={{
        height: 30,
        margin: 0,
        lineHeight: '30px',
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        color: 'var(--mut)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }}
    >
      {receipts.length ? `Done so far: ${receipts.join(' · ')}` : ''}
    </p>
  )
}
