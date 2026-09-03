// SOLUSDEV-235 / EXT-12 — host-side rail-icon SVG reduction (ADR-035 §3).
//
// The page icon is the ONE piece of extension-authored markup the HOST renders
// (in the rail, outside any sandbox), so it is reduced to a path-only,
// theme-aware subset before it can touch the DOM: a closed element set, a
// closed attribute allowlist, plain colours rewritten to `currentColor`, no
// DOCTYPE / entities / processing instructions / scripts / references. The
// rules are the publish-time Python reducer's (solus_api.extensions.svg) so the
// desktop never accepts what the registry would have refused.
import { MANIFEST_LIMITS } from '@solus/shared-types'

export const SVG_NAMESPACE = 'http://www.w3.org/2000/svg'

export const SVG_ALLOWED_ELEMENTS: ReadonlySet<string> = new Set([
  'svg',
  'g',
  'path',
  'circle',
  'rect',
  'line',
  'polyline',
  'polygon',
  'ellipse',
  'title'
])

/** `xmlns` is handled separately: allowed on any element only with the SVG namespace. */
export const SVG_ALLOWED_ATTRIBUTES: ReadonlySet<string> = new Set([
  'd',
  'cx',
  'cy',
  'r',
  'rx',
  'ry',
  'x',
  'y',
  'x1',
  'y1',
  'x2',
  'y2',
  'width',
  'height',
  'viewBox',
  'points',
  'fill',
  'stroke',
  'stroke-width',
  'stroke-linecap',
  'stroke-linejoin',
  'fill-rule',
  'opacity',
  'transform'
])

const COLOUR_ATTRIBUTES = new Set(['fill', 'stroke'])
/** `none`, `currentColor`, #rgb/#rgba/#rrggbb/#rrggbbaa, or a bare colour name. No url(), no rgb(). */
const COLOUR_RE =
  /^(none|currentColor|#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|[A-Za-z]+)$/
const FORBIDDEN_MARKUP_RE = /<!\s*(DOCTYPE|ENTITY)/i
/** Any processing instruction other than the XML declaration itself. */
const PROCESSING_INSTRUCTION_RE = /<\?(?!xml[\s?])/i

interface ReducedNode {
  readonly name: string
  readonly attrs: readonly (readonly [string, string])[]
  readonly children: readonly ReducedNode[]
  readonly text: string
}

const escapeText = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escapeAttr = (s: string): string =>
  escapeText(s).replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

function reduceAttribute(attr: Attr): readonly [string, string] | null | undefined {
  const { name, value } = attr
  if (name.toLowerCase().startsWith('on')) return null
  // The root re-adds xmlns; on any element it may only name the SVG namespace.
  if (name === 'xmlns') return value === SVG_NAMESPACE ? undefined : null
  if (!SVG_ALLOWED_ATTRIBUTES.has(name)) return null
  if (COLOUR_ATTRIBUTES.has(name)) {
    if (!COLOUR_RE.test(value)) return null
    return [name, value === 'none' ? 'none' : 'currentColor']
  }
  return [name, value]
}

/** Attributes kept, or null on any disallowed one (undefined entries are dropped xmlns). */
function reduceAttributes(el: Element): (readonly [string, string])[] | null {
  const kept: (readonly [string, string])[] = []
  for (const attr of Array.from(el.attributes)) {
    const reduced = reduceAttribute(attr)
    if (reduced === null) return null
    if (reduced !== undefined) kept.push(reduced)
  }
  return kept
}

function reduceElement(el: Element): ReducedNode | null {
  const name = el.tagName
  if (!SVG_ALLOWED_ELEMENTS.has(name)) return null
  const attrs = reduceAttributes(el)
  if (attrs === null) return null
  const children: ReducedNode[] = []
  let text = ''
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      const reduced = reduceElement(child as Element)
      if (reduced === null) return null
      children.push(reduced)
    } else if (child.nodeType === Node.TEXT_NODE || child.nodeType === Node.CDATA_SECTION_NODE) {
      if (name === 'title') text += child.nodeValue ?? ''
    } else if (child.nodeType === Node.PROCESSING_INSTRUCTION_NODE) {
      return null
    }
    // Comments are dropped.
  }
  return { name, attrs, children, text }
}

function serialize(node: ReducedNode): string {
  const attrs = node.attrs.map(([k, v]) => ` ${k}="${escapeAttr(v)}"`).join('')
  const inner = escapeText(node.text) + node.children.map(serialize).join('')
  return inner ? `<${node.name}${attrs}>${inner}</${node.name}>` : `<${node.name}${attrs}/>`
}

function parseSvg(text: string): Element | null {
  let doc: Document
  try {
    doc = new DOMParser().parseFromString(text, 'image/svg+xml')
  } catch {
    return null
  }
  if (doc.getElementsByTagName('parsererror').length > 0) return null
  const root = doc.documentElement
  return root && root.tagName === 'svg' ? root : null
}

/**
 * Reduce an icon to the allowed subset, or null when it is not acceptable
 * (oversized, DOCTYPE/ENTITY/PI, malformed, disallowed element/attribute,
 * non-plain colour). The output is itself valid input (idempotent) and is the
 * ONLY string `ExtensionIcon` will ever place in the DOM.
 */
export function reduceSvg(
  text: string,
  maxBytes: number = MANIFEST_LIMITS.iconBytes
): string | null {
  if (new TextEncoder().encode(text).byteLength > maxBytes) return null
  if (FORBIDDEN_MARKUP_RE.test(text) || PROCESSING_INSTRUCTION_RE.test(text)) return null
  const root = parseSvg(text)
  if (root === null) return null
  const reduced = reduceElement(root)
  if (reduced === null) return null
  return serialize({ ...reduced, attrs: [['xmlns', SVG_NAMESPACE], ...reduced.attrs] })
}
