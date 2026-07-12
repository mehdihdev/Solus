// SOLUSDEV-147 — pure functions behind the single-source-of-truth env system.
//
// `.env.mega` is the one file a developer fills in; every per-package env file
// is generated from it. This module contains NO filesystem access and logs
// nothing, so it is fully unit-testable and safe to reason about (CLAUDE.md §7:
// secret values never touch logs). The CLI wrapper (env-sync.mjs) does the I/O.
//
// Format: `# >>> <path>` headers split the file into blocks; each block's
// KEY=VALUE lines are written verbatim to <path>. The special `# >>> common`
// block is never written — it exists only so shared secrets can be defined once
// and referenced via ${VAR} interpolation from later blocks.

const HEADER_RE = /^#\s*>>>\s*(.+?)\s*$/;
const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const COMMON = "common";

// Characters that force a target value to be quoted. Anything outside this set
// (commas, spaces, '#', quotes, backslashes, ...) triggers double-quoting.
const BARE_SAFE_RE = /^[A-Za-z0-9_.\-:/@]*$/;

/**
 * Parse `.env.mega` text into ordered blocks. Raw values are preserved exactly;
 * quote/comment/interpolation handling happens later in {@link splitToTargets}.
 * @returns {{blocks: {path: string, isCommon: boolean, entries: {key: string, value: string}[]}[]}}
 */
export function parseMega(text) {
  const blocks = [];
  let current = null;

  text.split(/\r?\n/).forEach((line, i) => {
    const header = line.match(HEADER_RE);
    if (header) {
      const path = header[1];
      current = { path, isCommon: path === COMMON, entries: [] };
      blocks.push(current);
      return;
    }
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("#")) return; // blank / comment

    const eq = line.indexOf("=");
    if (eq === -1) {
      throw new Error(
        `env.mega line ${i + 1}: expected KEY=VALUE, got "${line}"`,
      );
    }
    const key = line.slice(0, eq).trim();
    if (!current) {
      throw new Error(
        `env.mega line ${i + 1}: "${key}" appears before any "# >>> <path>" header`,
      );
    }
    if (!KEY_RE.test(key)) {
      throw new Error(`env.mega line ${i + 1}: invalid key name "${key}"`);
    }
    current.entries.push({ key, value: line.slice(eq + 1) });
  });

  return { blocks };
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
 * Parse + resolve interpolation + serialize. Returns the concrete files to
 * write ({path, content}), excluding the non-emitted `common` block.
 * Scope for a block = resolved common values + its own earlier keys.
 */
export function splitToTargets(text) {
  const { blocks } = parseMega(text);

  const common = {};
  for (const block of blocks.filter((b) => b.isCommon)) {
    for (const { key, value } of block.entries) {
      common[key] = resolveValue(value, common); // may reference earlier common keys
    }
  }

  return blocks
    .filter((b) => !b.isCommon)
    .map((block) => {
      const scope = { ...common };
      const entries = block.entries.map(({ key, value }) => {
        const resolved = resolveValue(value, scope);
        scope[key] = resolved; // later keys may reference earlier ones
        return { key, value: resolved };
      });
      return { path: block.path, content: serializeEntries(entries) };
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
 * Render a `.env.mega` from concrete files (for gather). Produces one block per
 * file with a `# >>> <path>` header; round-trips through {@link splitToTargets}.
 */
export function renderMega(files, { header = DEFAULT_MEGA_HEADER } = {}) {
  const blocks = files.map(({ path, entries }) => {
    const lines = [
      `# >>> ${path}`,
      ...entries.map(({ key, value }) => `${key}=${serializeMegaValue(value)}`),
    ];
    return lines.join("\n");
  });
  return `${header}\n${blocks.join("\n\n")}\n`;
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
  "# `# >>> <path>` starts a block written to <path>. `# >>> common` is not",
  "# written; use it + ${VAR} to define shared secrets once. Single-quoted",
  "# values are literal; bare/double-quoted values interpolate ${VAR}.",
  "# NEVER commit this file — it holds secrets (.gitignore covers it).",
].join("\n");
