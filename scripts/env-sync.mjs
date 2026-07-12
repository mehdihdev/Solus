#!/usr/bin/env node
// SOLUSDEV-147 — the env CLI. Run by a human via pnpm; agents cannot touch
// .env* files (hooks H1/read_hook) but this script, run by you, does the I/O.
//
//   pnpm env:sync     .env.mega  ->  every per-package env file (overwrite)
//   pnpm env:gather   existing env files  ->  .env.mega (one-time bootstrap)
//
// Prints file paths and KEY names only — never a secret value (CLAUDE.md §7).
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  splitToTargets,
  parseEnvFile,
  renderMega,
  diffKeys,
  DEFAULT_MEGA_HEADER,
} from "./lib/env-mega.mjs";

// Repo root by default; ENV_SYNC_ROOT lets tests point the CLI at a temp tree.
const ROOT = process.env.ENV_SYNC_ROOT
  ? resolve(process.env.ENV_SYNC_ROOT)
  : resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MEGA = resolve(ROOT, ".env.mega");

// Files gather reads. sync is data-driven from the mega's headers instead.
const TARGET_FILES = [
  ".aws.env",
  "apps/desktop/.env",
  "apps/desktop/.env.claude",
  "packages/api/.env",
  "packages/api/.env.claude",
];

const log = (m) => process.stdout.write(`${m}\n`);
const die = (m) => {
  process.stderr.write(`[env] ${m}\n`);
  process.exit(1);
};

/** Resolve a mega-declared path and refuse anything escaping the repo root. */
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
  const targets = splitToTargets(readFileSync(MEGA, "utf8"));
  if (targets.length === 0)
    die(".env.mega has no `# >>> <path>` blocks to write.");

  for (const { path, content } of targets) {
    const abs = safeResolve(path);
    const megaKeys = keysOf(content);

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
    log(`  ✓ ${path} (${megaKeys.length} keys: ${megaKeys.join(", ")})`);
  }
  log(`Synced ${targets.length} file(s) from .env.mega.`);
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

  writeFileSync(MEGA, renderMega(files, { header: DEFAULT_MEGA_HEADER }));
  log(
    `Wrote .env.mega from ${files.length} file(s). Review it, then use "pnpm env:sync" going forward.`,
  );
}

const cmd = process.argv[2];
if (cmd === "sync") sync();
else if (cmd === "gather") gather();
else die(`unknown command "${cmd ?? ""}". Use "sync" or "gather".`);
