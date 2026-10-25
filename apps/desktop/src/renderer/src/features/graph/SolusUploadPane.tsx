// The Add modal's `.solus` pane (design template): a dashed dropzone. Files go through
// the existing .solus import handler (8 MiB cap, honest toasts) into the named section.
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'

export function SolusUploadPane({
  target,
  onChoose,
  onDrop
}: {
  /** The section label the files land in, e.g. `Documentation`. */
  target: string
  onChoose: () => void
  onDrop: (files: File[]) => void
}): React.JSX.Element {
  return (
    <div className="add-modal-pane" role="tabpanel">
      <button
        type="button"
        className="add-dropzone"
        aria-label="Upload documents"
        onClick={onChoose}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          const files = Array.from(event.dataTransfer.files)
          if (files.length) onDrop(files)
        }}
      >
        <Icons.file size={22} />
        <span>Drop documents here or click to choose</span>
        <Mono size={10}>MD · PDF · CSV · PNG — saved to .solus › {target}</Mono>
      </button>
    </div>
  )
}
