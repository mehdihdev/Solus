// SOLUSDEV-147 — pure functions behind the single-source-of-truth env system.
//
// `.env.mega` is the one file a developer fills in; every per-package env file
// is generated from it. This module contains NO filesystem access and logs
// nothing, so it is fully unit-testable and safe to reason about (CLAUDE.md §7:
// secret values never touch logs). The CLI wrapper (env-sync.mjs) does the I/O.
//
// Format (flat model): `.env.mega` is a flat list of KEY=VALUE lines. There are
// no per-file routing headers — `pnpm env:sync` writes the ENTIRE resolved file
// verbatim into every target env file, and each consumer reads only the keys it
// recognises (pydantic Settings ignores non-SOLUS_ keys; Vite exposes only
// VITE_*; the waitlist route reads only GOOGLE_*). Shared values are defined
// once and reused via ${VAR}: any key may reference an earlier key.
//
// Lines beginning with `#` are comments (this includes any legacy `# >>> path`
// routing headers, which are now ignored). Single-quoted values are literal;
// bare and "double-quoted" values interpolate ${VAR}.

const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

// Characters that force a target value to be quoted. Anything outside this set
// (commas, spaces, '#', quotes, backslashes, ...) triggers double-quoting.
const BARE_SAFE_RE = /^[A-Za-z0-9_.\-:/@]*$/;

/**
 * Parse `.env.mega` text into an ordered, de-duplicated list of raw entries.
 * Raw values are preserved exactly; quote/comment/interpolation handling
 * happens later in {@link resolveMega}. Duplicate keys keep first-seen order
 * with the LAST value winning (standard dotenv semantics).
 * @returns {{entries: {key: string, value: string}[]}}
 */
export function parseMega(text) {
  const order = [];
  const values = new Map();

  text.split(/\r?\n/).forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("#")) return; // blank / comment (incl. legacy `# >>>`)

    const eq = line.indexOf("=");
    if (eq === -1) {
      throw new Error(
        `env.mega line ${i + 1}: expected KEY=VALUE, got "${line}"`,
      );
    }
    const key = line.slice(0, eq).trim();
    if (!KEY_RE.test(key)) {
      throw new Error(`env.mega line ${i + 1}: invalid key name "${key}"`);
    }
    if (!values.has(key)) order.push(key);
    values.set(key, line.slice(eq + 1));
  });

  return { entries: order.map((key) => ({ key, value: values.get(key) })) };
}

/**
 * Resolve a single raw value (right-hand side of `=`) against a scope map.
 * Single-quoted → literal. Double-quoted → unescaped + interpolated. Bare →
 * inline-comment stripped, then interpolated.
 */
function resolveValue(raw, scope) {
  const v = raw.trim();

  if (v.startsWith("'") && v.endsWith("'") && v.length >= 2) {
    return v.slice(1, -1); // literal, no interpolation
  }
  if (v.startsWith('"') && v.endsWith('"') && v.length >= 2) {
    return expandDouble(v.slice(1, -1), scope);
  }
  return interpolate(stripInlineComment(v), scope);
}

/**
 * Expand a double-quoted body: process `\X` escapes (\$ → literal $, \" → ",
 * \\ → \, \n → newline) and ${VAR} references in one left-to-right pass, so an
 * escaped `\$` is consumed before it can start an interpolation.
 */
function expandDouble(inner, scope) {
  return inner.replace(
    /\\([\s\S])|\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g,
    (_, esc, name) => {
      if (esc !== undefined) return esc === "n" ? "\n" : esc;
      if (!(name in scope)) {
        throw new Error(`env.mega: unresolved reference \${${name}}`);
      }
      return scope[name];
    },
  );
}

/** Strip a ` #...` trailing comment from a bare value (space required before #). */
function stripInlineComment(v) {
  const m = v.match(/\s+#/);
  return (m ? v.slice(0, m.index) : v).trim();
}

/** Replace ${VAR} using `scope`; throw naming any unresolved variable. */
function interpolate(value, scope) {
  return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, name) => {
    if (!(name in scope)) {
      throw new Error(`env.mega: unresolved reference \${${name}}`);
    }
    return scope[name];
  });
}

/**
 * Parse + resolve interpolation for the whole flat file. Every key is emitted;
 * a key may reference any earlier key via ${VAR}. Returns the resolved
 * {key, value} entries in file order.
 * @returns {{key: string, value: string}[]}
 */
export function resolveMega(text) {
  const { entries } = parseMega(text);
  const scope = {};
  return entries.map(({ key, value }) => {
    const resolved = resolveValue(value, scope);
    scope[key] = resolved; // later keys may reference earlier ones
    return { key, value: resolved };
  });
}

/** Parse a real `.env` file (for gather). Tolerates `export ` and quotes. */
export function parseEnvFile(text) {
  const entries = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    const withoutExport = trimmed.replace(/^export\s+/, "");
    const eq = withoutExport.indexOf("=");
    if (eq === -1) continue;
    const key = withoutExport.slice(0, eq).trim();
    if (!KEY_RE.test(key)) continue;
    entries.push({ key, value: unquote(withoutExport.slice(eq + 1).trim()) });
  }
  return entries;
}

function unquote(v) {
  if (
    v.length >= 2 &&
    (v.startsWith('"') || v.startsWith("'")) &&
    v.endsWith(v[0])
  ) {
    const inner = v.slice(1, -1);
    return v[0] === '"'
      ? inner.replace(/\\(["\\n])/g, (_, c) => (c === "n" ? "\n" : c))
      : inner;
  }
  return stripInlineComment(v);
}

/** Serialize entries for a TARGET env file (consumed by vite/python-dotenv/bash). */
export function serializeEntries(entries) {
  return (
    entries
      .map(({ key, value }) => `${key}=${serializeTargetValue(value)}`)
      .join("\n") + "\n"
  );
}

function serializeTargetValue(v) {
  if (v === "") return "";
  if (BARE_SAFE_RE.test(v)) return v;
  return `"${v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
}

/**
 * Serialize a value for the MEGA file. Double-quotes anything not bare-safe,
 * escaping `\ " \n` and `$` (as `\$`) so gather round-trips values containing a
 * literal `$` without sync interpolating them — and without losing any `'`.
 */
function serializeMegaValue(v) {
  if (v === "") return "";
  if (BARE_SAFE_RE.test(v)) return v;
  return `"${v
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\n")
    .replace(/\$/g, "\\$")}"`;
}

/**
 * Merge entries gathered from several existing env files into one de-duplicated
 * list (first file wins, preserving first-seen order). Returns the merged
 * entries plus any conflicts (same key, differing value) for the caller to warn
 * about — never the values themselves are logged by callers (CLAUDE.md §7).
 * @returns {{entries: {key: string, value: string}[], conflicts: string[]}}
 */
export function mergeEnvFiles(files) {
  const order = [];
  const chosen = new Map();
  const conflicts = new Set();
  for (const { entries } of files) {
    for (const { key, value } of entries) {
      if (!chosen.has(key)) {
        order.push(key);
        chosen.set(key, value);
      } else if (chosen.get(key) !== value) {
        conflicts.add(key); // keep the first value; flag the divergence
      }
    }
  }
  return {
    entries: order.map((key) => ({ key, value: chosen.get(key) })),
    conflicts: [...conflicts],
  };
}

/**
 * Render a flat `.env.mega` from resolved entries (for gather). Round-trips
 * through {@link resolveMega}: a literal `$` is escaped so it is not treated as
 * an interpolation on the next sync.
 */
export function renderMega(entries, { header = DEFAULT_MEGA_HEADER } = {}) {
  const body = entries
    .map(({ key, value }) => `${key}=${serializeMegaValue(value)}`)
    .join("\n");
  return `${header}\n\n${body}\n`;
}

/** Keys present in the existing target but absent from the mega (would be lost). */
export function diffKeys(existingKeys, megaKeys) {
  const covered = new Set(megaKeys);
  return existingKeys.filter((k) => !covered.has(k));
}

export const DEFAULT_MEGA_HEADER = [
  "# .env.mega — single source of truth for every env file (SOLUSDEV-147).",
  "# Fill this in, then run:  pnpm env:sync",
  "# Bootstrap from existing files:  pnpm env:gather",
  "#",
  "# Flat KEY=VALUE list. `pnpm env:sync` writes this ENTIRE file (with ${VAR}",
  "# interpolation resolved) verbatim into every target env file; each consumer",
  "# reads only the keys it recognises. Define a shared value once and reference",
  "# it later via ${VAR}. Single-quoted values are literal; bare/double-quoted",
  "# values interpolate. NEVER commit this file — it holds secrets (.gitignore).",
].join("\n");
