#!/usr/bin/env node
// SOLUSDEV-147 — the env CLI. Run by a human via pnpm; agents cannot touch
// .env* files (hooks H1/read_hook) but this script, run by you, does the I/O.
//
//   pnpm env:sync     .env.mega  ->  every target env file (whole file, overwrite)
//   pnpm env:gather   existing env files  ->  .env.mega (one-time bootstrap)
//
// Flat model (SOLUSDEV-164): sync writes the ENTIRE resolved .env.mega verbatim
// into each target below — no per-file key routing. Each consumer reads only
// the keys it recognises (pydantic ignores non-SOLUS_ keys; Vite exposes VITE_*
// only; the web waitlist route reads GOOGLE_* only).
//
// Prints file paths and KEY names only — never a secret value (CLAUDE.md §7).
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  resolveMega,
  parseEnvFile,
  serializeEntries,
  mergeEnvFiles,
  renderMega,
  diffKeys,
  DEFAULT_MEGA_HEADER,
} from "./lib/env-mega.mjs";

// Repo root by default; ENV_SYNC_ROOT lets tests point the CLI at a temp tree.
const ROOT = process.env.ENV_SYNC_ROOT
  ? resolve(process.env.ENV_SYNC_ROOT)
  : resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MEGA = resolve(ROOT, ".env.mega");

// The files sync writes and gather reads. The whole mega goes to each.
// Dropped vs the old block model (SOLUSDEV-164): the `.env.claude` agent-run
// profiles (whole-file sync makes them byte-identical to `.env`, and no code
// reads them) and `.aws.env` (deploy vars are GitLab CI-scoped, not in-repo).
const TARGET_FILES = [
  ".env",
  "apps/desktop/.env",
  "apps/web/.env",
  "packages/api/.env",
];

const log = (m) => process.stdout.write(`${m}\n`);
const die = (m) => {
  process.stderr.write(`[env] ${m}\n`);
  process.exit(1);
};

/** Resolve a target path and refuse anything escaping the repo root. */
function safeResolve(relPath) {
  const abs = resolve(ROOT, relPath);
  const rel = relative(ROOT, abs);
  if (rel.startsWith("..") || rel.startsWith(sep) || rel === "") {
    die(`refusing to write outside the repo: "${relPath}"`);
  }
  return abs;
}

function keysOf(text) {
  return parseEnvFile(text).map((e) => e.key);
}

function sync() {
  if (!existsSync(MEGA)) {
    die(
      `.env.mega not found. Run "pnpm env:gather" to bootstrap it, or "cp env.mega.example .env.mega" and fill it in.`,
    );
  }
  const entries = resolveMega(readFileSync(MEGA, "utf8"));
  if (entries.length === 0) die(".env.mega has no KEY=VALUE lines to write.");

  const content = serializeEntries(entries);
  const megaKeys = entries.map((e) => e.key);

  for (const path of TARGET_FILES) {
    const abs = safeResolve(path);
    if (existsSync(abs)) {
      const dropped = diffKeys(keysOf(readFileSync(abs, "utf8")), megaKeys);
      if (dropped.length) {
        log(
          `  ! ${path}: overwriting; these keys exist there but not in .env.mega and will be dropped: ${dropped.join(", ")}`,
        );
      }
    }
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, content);
    log(`  ✓ ${path}`);
  }
  log(
    `Synced ${megaKeys.length} keys → ${TARGET_FILES.length} file(s): ${megaKeys.join(", ")}`,
  );
}

function gather() {
  const force = process.argv.includes("--force");
  if (existsSync(MEGA) && !force) {
    die(
      `.env.mega already exists. Re-run with --force to overwrite it (you will lose any hand edits).`,
    );
  }

  const files = [];
  for (const rel of TARGET_FILES) {
    const abs = resolve(ROOT, rel);
    if (!existsSync(abs)) {
      log(`  - ${rel}: not present, skipped`);
      continue;
    }
    const entries = parseEnvFile(readFileSync(abs, "utf8"));
    files.push({ path: rel, entries });
    log(`  ✓ ${rel} (${entries.length} keys)`);
  }
  if (files.length === 0) die("no existing env files found to gather.");

  const { entries, conflicts } = mergeEnvFiles(files);
  if (conflicts.length) {
    log(
      `  ! keys with differing values across files (kept the first occurrence): ${conflicts.join(", ")}`,
    );
  }
  writeFileSync(MEGA, renderMega(entries, { header: DEFAULT_MEGA_HEADER }));
  log(
    `Wrote .env.mega with ${entries.length} keys from ${files.length} file(s). Review it, then use "pnpm env:sync" going forward.`,
  );
}

const cmd = process.argv[2];
if (cmd === "sync") sync();
else if (cmd === "gather") gather();
else die(`unknown command "${cmd ?? ""}". Use "sync" or "gather".`);
