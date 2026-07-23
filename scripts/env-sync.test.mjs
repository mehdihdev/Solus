// SOLUSDEV-147 / SOLUSDEV-164 — integration tests for the env CLI against a
// temp tree. Exercises the flat sync/gather I/O without touching real .env
// files, plus the template-completeness suite: env.mega.example is the single
// onboarding checklist, so its required shape is asserted executably.
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  writeFileSync,
  readFileSync,
  mkdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveMega } from "./lib/env-mega.mjs";

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const CLI = resolve(SCRIPTS_DIR, "env-sync.mjs");
const EXAMPLE = resolve(SCRIPTS_DIR, "..", "env.mega.example");

// The files sync writes / gather reads, mirrored from env-sync.mjs TARGET_FILES.
const TARGETS = [
  ".env",
  "apps/desktop/.env",
  "apps/web/.env",
  "packages/api/.env",
];
let root;

const run = (args, extraEnv = {}) =>
  execFileSync("node", [CLI, ...args], {
    env: { ...process.env, ENV_SYNC_ROOT: root, ...extraEnv },
    encoding: "utf8",
  });

const runExpectFail = (args) => {
  try {
    run(args);
    return null;
  } catch (e) {
    return `${e.stdout ?? ""}${e.stderr ?? ""}`;
  }
};

const write = (rel, text) => {
  const abs = join(root, rel);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, text);
};
const read = (rel) => readFileSync(join(root, rel), "utf8");

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "envsync-"));
});
afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

test("sync writes the WHOLE resolved mega into every target file", () => {
  write(
    ".env.mega",
    [
      "SUPABASE_URL=https://x.supabase.co",
      "VITE_SUPABASE_URL=${SUPABASE_URL}",
      "SOLUS_DATABASE_URL=postgres://a/b",
    ].join("\n"),
  );

  const out = run(["sync"]);
  for (const t of TARGETS)
    assert.match(out, new RegExp(t.replace(/[.\\/]/g, "\\$&")));
  assert.match(out, /VITE_SUPABASE_URL/); // key is logged
  assert.doesNotMatch(out, /supabase\.co/); // value is NOT logged (§7)

  // Every target gets the full set — no per-file routing anymore.
  for (const t of TARGETS) {
    const written = read(t);
    assert.match(written, /VITE_SUPABASE_URL=https:\/\/x\.supabase\.co/);
    assert.match(written, /SOLUS_DATABASE_URL=postgres:\/\/a\/b/);
  }
});

test("sync warns about keys that exist in a target but not the mega", () => {
  write("packages/api/.env", "SOLUS_DATABASE_URL=old\nSOLUS_LEGACY=drop_me\n");
  write(".env.mega", "SOLUS_DATABASE_URL=new\n");

  const out = run(["sync"]);
  assert.match(out, /SOLUS_LEGACY/);
  assert.match(out, /dropped/i);
  assert.match(read("packages/api/.env"), /SOLUS_DATABASE_URL=new/);
});

test("sync fails clearly when .env.mega is absent", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  assert.match(runExpectFail(["sync"]), /env\.mega not found/i);
});

test("gather merges existing files into one flat mega and round-trips via sync", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(
    "apps/web/.env",
    "export GOOGLE_SHEETS_SPREADSHEET_ID=sheet123\nGOOGLE_SHEETS_RANGE=WaitlistA:C\n",
  );
  write("packages/api/.env", 'SOLUS_DATABASE_URL="postgres://a b/c"\n');

  const out = run(["gather"]);
  assert.match(out, /apps\/web\/\.env/);
  const mega = read(".env.mega");
  assert.doesNotMatch(mega, /# >>>/); // flat, no routing headers
  assert.match(mega, /GOOGLE_SHEETS_SPREADSHEET_ID=sheet123/);
  assert.match(mega, /SOLUS_DATABASE_URL="postgres:\/\/a b\/c"/);

  // The gathered mega must sync back to valid files (whole file → each target).
  run(["sync"]);
  assert.match(read("apps/web/.env"), /GOOGLE_SHEETS_RANGE=WaitlistA:C/);
  assert.match(
    read("packages/api/.env"),
    /SOLUS_DATABASE_URL="postgres:\/\/a b\/c"/,
  );
});

test("gather flags keys whose value differs across files (keeps the first)", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(".env", "SOLUS_TRIAL_DAYS=30\n");
  write("packages/api/.env", "SOLUS_TRIAL_DAYS=14\n");

  const out = run(["gather"]);
  assert.match(out, /SOLUS_TRIAL_DAYS/);
  assert.match(read(".env.mega"), /SOLUS_TRIAL_DAYS=30/); // first (root .env) wins
});

test("gather refuses to clobber an existing .env.mega without --force", () => {
  writeFileSync(join(root, ".env.mega"), "SOLUS_DATABASE_URL=keep\n");
  assert.match(runExpectFail(["gather"]), /already exists/i);
  assert.match(read(".env.mega"), /SOLUS_DATABASE_URL=keep/); // untouched

  write("packages/api/.env", "SOLUS_DATABASE_URL=fresh\n");
  run(["gather", "--force"]); // now allowed
  assert.match(read(".env.mega"), /SOLUS_DATABASE_URL=fresh/);
});

test("unknown subcommand fails with usage", () => {
  assert.match(runExpectFail(["frobnicate"]), /unknown command/i);
});

// --- WS-C: env.mega.example completeness -------------------------------------
// The committed template IS the onboarding checklist: cp → fill → env:sync must
// yield a boot-ready backend + desktop + web. These tests pin the template to
// the consuming code (config.py Settings, client.ts, waitlist route.js).

// Every SOLUS_* key the backend Settings consumes (core/config.py). The backend
// keeps env_prefix="SOLUS_", so these prefixes MUST survive into the template.
const REQUIRED_API_KEYS = [
  "SOLUS_APP_ENV",
  "SOLUS_API_VERSION",
  "SOLUS_BUILD_SHA",
  "SOLUS_DATABASE_URL",
  "SOLUS_REDIS_URL",
  "SOLUS_CORS_ORIGINS",
  "SOLUS_AUTO_CREATE_TABLES",
  "SOLUS_SUPABASE_JWT_SECRET",
  "SOLUS_SUPABASE_JWT_AUDIENCE",
  "SOLUS_RATE_LIMIT_PER_MINUTE",
  "SOLUS_CLASSIFY_RATE_LIMIT_PER_MINUTE",
  "SOLUS_INVITE_TTL_DAYS",
  "SOLUS_TRIAL_DAYS",
  "SOLUS_STRIPE_WEBHOOK_SECRET",
  "SOLUS_STRIPE_PACK_CREDITS",
  "SOLUS_STRIPE_WEBHOOK_MAX_BYTES",
  "SOLUS_TRIAL_CREDIT_GRANT",
  "SOLUS_SECRETS_KEY",
  "SOLUS_AWS_REGION",
  "SOLUS_GITHUB_CLIENT_ID",
  "SOLUS_GITHUB_CLIENT_SECRET",
  "SOLUS_GITLAB_CLIENT_ID",
  "SOLUS_GITLAB_CLIENT_SECRET",
  "SOLUS_GITLAB_BASE_URL",
  "SOLUS_GITHUB_OAUTH_REDIRECT_APP",
  "SOLUS_PUBLIC_API_BASE_URL",
  "SOLUS_SYNC_INLINE",
  "SOLUS_FINGERPRINT_LLM_ENABLED",
  "SOLUS_FINGERPRINT_EMBEDDING_ENABLED",
  "SOLUS_FINGERPRINT_VISION_ENABLED",
];

const exampleEntries = () => resolveMega(readFileSync(EXAMPLE, "utf8"));
const exampleKeys = () => new Set(exampleEntries().map((e) => e.key));
const exampleValue = (key) =>
  exampleEntries().find((e) => e.key === key)?.value;

test("env.mega.example parses as a flat file (no dead routing headers)", () => {
  const raw = readFileSync(EXAMPLE, "utf8");
  assert.doesNotMatch(raw, /# >>>/);
  assert.ok(exampleEntries().length > 0);
});

test("env.mega.example carries every consumed SOLUS_* key with its prefix", () => {
  const keys = exampleKeys();
  for (const key of REQUIRED_API_KEYS)
    assert.ok(keys.has(key), `template is missing ${key}`);
});

test("env.mega.example covers the desktop VITE_* and web GOOGLE_* keys", () => {
  const keys = exampleKeys();
  for (const key of [
    "VITE_API_BASE_URL",
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_ANON_KEY",
  ]) {
    assert.ok(keys.has(key), `template is missing ${key}`);
  }
  for (const key of [
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_SERVICE_ACCOUNT_EMAIL",
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    "GOOGLE_SHEETS_RANGE",
  ]) {
    assert.ok(keys.has(key), `template is missing ${key}`);
  }
});

test("env.mega.example matches code semantics (no drifted defaults)", () => {
  // client.ts falls back to http://localhost:8000/api/v1 — the template value
  // must keep the /api/v1 suffix or every API call 404s.
  assert.match(exampleValue("VITE_API_BASE_URL") ?? "", /\/api\/v1$/);
  // Schema is owned by Alembic migrations; create_all stays off.
  assert.equal(exampleValue("SOLUS_AUTO_CREATE_TABLES"), "false");
  // api_version is a semver reported by /meta, not a route prefix.
  assert.equal(exampleValue("SOLUS_API_VERSION"), "0.1.0");
});

test("env.mega.example documents SOLUS_SECRETS_BACKEND but ships it commented", () => {
  // build_secret_store auto-selects a backend only when secrets_backend is None
  // (unset). A blank `SOLUS_SECRETS_BACKEND=` becomes "" — not None — and
  // silently disables auto-selection. So the template documents it without emitting it.
  const raw = readFileSync(EXAMPLE, "utf8");
  assert.match(raw, /SOLUS_SECRETS_BACKEND/);
  assert.ok(
    !exampleKeys().has("SOLUS_SECRETS_BACKEND"),
    "SOLUS_SECRETS_BACKEND must stay commented",
  );
});

test("env.mega.example documents the SecretStore provisioning step for LLM keys", () => {
  const raw = readFileSync(EXAMPLE, "utf8");
  for (const ref of ["anthropic_api_key", "openai_api_key", "google_api_key"]) {
    assert.ok(raw.includes(ref), `template must name SecretStore ref ${ref}`);
  }
  assert.match(raw, /Secrets Manager/i);
});

test("env.mega.example holds no real-looking secret values", () => {
  for (const { key, value } of exampleEntries()) {
    if (!/(KEY|SECRET|TOKEN|PRIVATE)/.test(key)) continue;
    assert.ok(
      value === "" || /CHANGE_ME|changeme|\$\{/.test(value),
      `${key} must be blank or an obvious placeholder`,
    );
  }
});
