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
import { splitSettled, stableTail } from './markdownSplit'

const REMARK_PLUGINS = [remarkGfm]

const COMPONENTS: Components = {
  a: ({ children }) => <span className="sol-md-link">{children}</span>,
  img: () => null
}

export interface SolMarkdownProps {
  content: string
}

// One parse. memo: its string only changes when a block settles (or the tail
// grows), so a settled prefix is parsed once per block, not once per token.
const Blocks = memo(function Blocks({ content }: SolMarkdownProps): React.JSX.Element | null {
  if (!content) return null
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} skipHtml components={COMPONENTS}>
      {content}
    </ReactMarkdown>
  )
})

// SOLUSDEV-252 S2: two parses in ONE `.sol-md` container — the settled prefix
// (re-parsed only when a block completes) and the block still being written
// (re-parsed per token, but it is one block, not the whole reply). Sharing the
// container keeps the block-margin rules identical across the seam. memo on
// the outer component skips every settled MESSAGE entirely.
export const SolMarkdown = memo(function SolMarkdown({
  content
}: SolMarkdownProps): React.JSX.Element {
  const { settled, tail } = splitSettled(content)
  return (
    <div className="sol-md" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
      <Blocks content={settled} />
      <Blocks content={stableTail(tail)} />
    </div>
  )
})
