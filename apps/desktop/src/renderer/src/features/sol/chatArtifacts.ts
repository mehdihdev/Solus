// The ARTIFACTS panel's data (design template): everything SOL produced in the loaded
// conversation, deduped, in transcript order — live-session only, since reloaded turns
// carry no artifact bytes. Pure helpers, no fetches.
import type { ChatArtifact, ChatItem } from './solChatStore'

export function collectArtifacts(items: readonly ChatItem[]): ChatArtifact[] {
  const seen = new Set<string>()
  const out: ChatArtifact[] = []
  for (const item of items) {
    for (const artifact of item.artifacts ?? []) {
      if (seen.has(artifact.artifactId)) continue
      seen.add(artifact.artifactId)
      out.push(artifact)
    }
  }
  return out
}

const MAX_EXT = 4

/** The short mono label: the title's extension, else the media subtype — upper, ≤ 4 chars. */
export function artifactExt({ title, mediaType }: { title: string; mediaType: string }): string {
  const dot = title.lastIndexOf('.')
  const fromTitle = dot > 0 && dot < title.length - 1 ? title.slice(dot + 1) : ''
  const fromMedia = mediaType.split('/')[1]?.split('+')[0] ?? ''
  const ext = (fromTitle || fromMedia || 'FILE').toUpperCase()
  return ext.length > MAX_EXT ? ext.slice(0, MAX_EXT) : ext
}

/** Text we can put on the clipboard; everything else is bytes. */
export function isTextArtifact(mediaType: string): boolean {
  return (
    mediaType.startsWith('text/') ||
    ['application/json', 'application/xml', 'image/svg+xml'].includes(mediaType)
  )
}
