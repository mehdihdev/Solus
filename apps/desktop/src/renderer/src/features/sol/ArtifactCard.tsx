// SOLUSDEV-252 S5: a tool's artifact in the assistant row, after the trace.
//
// Bytes need the bearer (artifacts.md §4), so an `<img src={uri}>` would 401 —
// the card fetches through solApi, wraps the Blob in an object URL and shows it
// as an <img>. An <img> cannot run scripts inside an SVG, and the SVG text is
// never injected into the DOM (CLAUDE.md §7: model/tool output is untrusted).
// Titles and summaries render as React text nodes only.
//
// Filing ("File this to…?") is idempotent by construction: `filedTo` lives on
// the store item, so a remount or a second click cannot create a second entry.
import { useEffect, useState } from 'react'
import { Segmented } from '../../components/ui/Segmented'
import { SECTION_LABELS } from '../graph/useSolusConfig'
import { SOLUS_SECTIONS, type SolusSection } from '../../lib/api/resources'
import { fetchArtifactBlob } from './solApi'
import type { ChatArtifact } from './solChatStore'

export interface ArtifactCardProps {
  readonly projectId: string
  readonly artifact: ChatArtifact
  /** Rejects with the API's own error; the host marks `filedTo` on success. */
  readonly onFile: (section: SolusSection) => Promise<void>
}

const LABELS = SOLUS_SECTIONS.map((s) => SECTION_LABELS[s])
const sectionOf = (label: string): SolusSection => SOLUS_SECTIONS[LABELS.indexOf(label)] ?? 'docs'

/** The object URL for an image artifact: null while loading, the URL, or false
 *  when the bytes could not be fetched. Revoked on unmount. */
function useArtifactUrl(projectId: string, artifact: ChatArtifact): string | null | false {
  const [url, setUrl] = useState<string | null | false>(null)
  const isImage = artifact.mediaType.startsWith('image/')
  useEffect(() => {
    if (!isImage) return
    let objectUrl: string | null = null
    let live = true
    fetchArtifactBlob(projectId, artifact.artifactId)
      .then((blob) => {
        if (!live) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => live && setUrl(false))
    return () => {
      live = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [projectId, artifact.artifactId, isImage])
  return isImage ? url : false
}

function ArtifactBody({
  artifact,
  url
}: {
  artifact: ChatArtifact
  url: string | null | false
}): React.JSX.Element {
  if (!artifact.mediaType.startsWith('image/')) {
    return (
      <div className="sol-artifact-chip">
        <span>{artifact.title}</span>
        <span className="sol-artifact-type">{artifact.mediaType}</span>
      </div>
    )
  }
  if (url === null) return <div className="sol-artifact-note">loading…</div>
  if (url === false) return <div className="sol-artifact-note">Couldn’t load this image.</div>
  return <img className="sol-artifact-img" src={url} alt={artifact.title} />
}

function FileRow({
  artifact,
  onFile
}: Pick<ArtifactCardProps, 'artifact' | 'onFile'>): React.JSX.Element | null {
  const [section, setSection] = useState<SolusSection>('docs')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [kept, setKept] = useState(false)
  if (artifact.filedTo !== null) {
    return <div className="sol-artifact-note">Filed to {SECTION_LABELS[artifact.filedTo]}</div>
  }
  if (kept) return null
  const file = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await onFile(section)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That didn’t go through.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="sol-artifact-file">
      <span className="sol-artifact-note">File this to…?</span>
      <Segmented
        size="sm"
        ariaLabel="Section"
        options={LABELS}
        value={SECTION_LABELS[section]}
        onChange={(label) => setSection(sectionOf(label))}
      />
      <button type="button" className="sol-region-ask" disabled={busy} onClick={() => void file()}>
        {busy ? 'Filing…' : 'File'}
      </button>
      <button type="button" className="sol-artifact-keep" onClick={() => setKept(true)}>
        Keep in chat
      </button>
      {error && <div className="sol-artifact-error">{error}</div>}
    </div>
  )
}

export function ArtifactCard({
  projectId,
  artifact,
  onFile
}: ArtifactCardProps): React.JSX.Element {
  const url = useArtifactUrl(projectId, artifact)
  return (
    <section className="sol-artifact-card" aria-label={`Artifact: ${artifact.title}`}>
      <ArtifactBody artifact={artifact} url={url} />
      {artifact.summary && <div className="sol-artifact-note">{artifact.summary}</div>}
      <FileRow artifact={artifact} onFile={onFile} />
    </section>
  )
}
