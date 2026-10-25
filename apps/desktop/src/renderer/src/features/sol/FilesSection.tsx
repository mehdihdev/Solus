// FILES & IMAGES (design template, SOL page right column): the project's `.solus` file
// entries — what an upload here becomes — as a two-column grid of ext-labelled tiles.
// SOL reads `.solus` into every turn's context, by file NAME (the bytes never reach the
// model), and the copy says exactly that. Upload goes through the same import handler
// the Workspace uses (8 MiB cap, honest toasts).
import { useRef } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { SOLUS_SECTIONS, type SolusEntry } from '../../lib/api/resources'
import type { SolusState } from '../graph/useSolusConfig'
import { artifactExt } from './chatArtifacts'

export function solusFiles(sections: SolusState['sections']): SolusEntry[] {
  return SOLUS_SECTIONS.flatMap((section) => sections[section]).filter(
    (entry) => entry.kind === 'artifact'
  )
}

export function FilesSection({
  solus,
  onUpload
}: {
  solus: SolusState
  onUpload: (file: File) => void
}): React.JSX.Element {
  const input = useRef<HTMLInputElement | null>(null)
  const files = solusFiles(solus.sections)
  return (
    <section className="sol-side-section" aria-label="Files and images">
      <div className="sol-side-head">
        <Mono size={10} ls="0.08em">
          FILES &amp; IMAGES
        </Mono>
        <button
          type="button"
          className="sol-side-link"
          disabled={solus.status !== 'ready'}
          onClick={() => input.current?.click()}
        >
          + Upload
        </button>
        <input
          ref={input}
          type="file"
          aria-label="Upload file or image"
          style={{ display: 'none' }}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) onUpload(file)
          }}
        />
      </div>
      {solus.status === 'loading' && (
        <div className="sol-side-empty">
          <Spinner size={12} />
        </div>
      )}
      {solus.status === 'offline' && <p className="sol-side-empty">Unavailable offline.</p>}
      {solus.status === 'ready' && files.length === 0 && (
        <p className="sol-side-empty">
          No files yet. Uploads land in the project&apos;s .solus folder and SOL sees them by name.
        </p>
      )}
      {files.length > 0 && (
        <div className="sol-file-grid">
          {files.map((entry) => (
            <div key={entry.id} className="sol-file-tile" title={entry.name ?? undefined}>
              <div className="sol-file-ext">
                <Mono size={10}>
                  {artifactExt({ title: entry.name ?? '', mediaType: entry.media_type ?? '' })}
                </Mono>
              </div>
              <div className="sol-file-name">{entry.name ?? 'file'}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
