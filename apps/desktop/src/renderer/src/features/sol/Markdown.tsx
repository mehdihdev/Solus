// SOL's model text, rendered as markdown WITHOUT an HTML injection path
// (CLAUDE.md §7 — model output is untrusted):
// - react-markdown emits React elements only; there is no
//   dangerouslySetInnerHTML anywhere on this path, and `skipHtml` drops raw
//   HTML in the model text instead of parsing it into the DOM;
// - links render as inert dotted-underline text, never anchors — the renderer
//   has no navigation guard for model-supplied URLs (upgrade path: an anchor
//   that routes through shell.openExternal via preload, once a guard exists);
// - images are dropped — the CSP blocks remote sources, so they could only
//   ever render broken.
// Typography lives in main.css under `.sol-md`, design tokens only.
import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const REMARK_PLUGINS = [remarkGfm]

const COMPONENTS: Components = {
  a: ({ children }) => <span className="sol-md-link">{children}</span>,
  img: () => null
}

export interface SolMarkdownProps {
  content: string
}

// memo: during a stream every token patch re-renders the message list; all the
// SETTLED messages keep their content string, so memo skips their re-parse and
// only the growing message pays for one (bounded by MAX_TURN_CHARS upstream).
export const SolMarkdown = memo(function SolMarkdown({
  content
}: SolMarkdownProps): React.JSX.Element {
  return (
    <div className="sol-md" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} skipHtml components={COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
})
