// SOLUSDEV-252 S3, wireflow §C: the circled region above the composer — the
// crop (max 320 px wide, letterboxed), `<app> — <title>` when known, and the
// "What do you think this is?" ask. The pixels are rendered from memory as a
// data URL and never written anywhere. `source` strings are untrusted window
// titles (CLAUDE.md §7): rendered as React text nodes only.
import type { SolRegionPayload } from '../../../../main/sol-window/solWindow'

export const ASK_WHAT_IS_THIS = 'What do you think this is?'

interface RegionCardProps {
  region: SolRegionPayload
  onAsk: () => void
}

export function RegionCard({ region, onAsk }: RegionCardProps): React.JSX.Element {
  return (
    <div className="sol-region-card">
      <img
        className="sol-region-crop"
        src={`data:image/png;base64,${region.pngBase64}`}
        width={region.width}
        height={region.height}
        alt="Circled screen region"
      />
      {region.source && (
        <div className="sol-region-caption">
          {region.source.app} — {region.source.title}
        </div>
      )}
      <button type="button" className="sol-region-ask" onClick={onAsk}>
        {ASK_WHAT_IS_THIS}
      </button>
    </div>
  )
}
