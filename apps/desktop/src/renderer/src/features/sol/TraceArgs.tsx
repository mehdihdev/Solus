// SOLUSDEV-321 P1-T6: a tool step's arguments under its line in the trace. They arrive as the
// server's REDACTED copy, already cut to display size by the stream parser (solStream.toToolArgs),
// and are drawn as `key: value` text nodes — a model-proposed value is never markup here.
import type { ToolArgs } from './solStream'

const BLOCK: React.CSSProperties = {
  paddingLeft: 12,
  overflowWrap: 'anywhere',
  opacity: 0.85
}

export function TraceArgs({ args }: { args: ToolArgs | undefined }): React.JSX.Element | null {
  const rows = args ? Object.entries(args) : []
  if (rows.length === 0) return null
  return (
    <div data-testid="tool-args" style={BLOCK}>
      {rows.map(([key, value]) => (
        <div key={key}>{`${key}: ${value}`}</div>
      ))}
    </div>
  )
}
