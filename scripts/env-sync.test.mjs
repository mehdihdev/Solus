// SOLUSDEV-147 — integration tests for the env CLI against a temp tree.
// Exercises sync/gather I/O without ever touching the real .env files.
// SOLUSDEV-152 adds the template-completeness suite: env.mega.example is the
// single onboarding checklist, so its required shape is asserted executably.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  writeFileSync,
  readFileSync,
  existsSync,
  mkdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { splitToTargets, parseEnvFile } from "./lib/env-mega.mjs";

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const CLI = resolve(SCRIPTS_DIR, "env-sync.mjs");
const EXAMPLE = resolve(SCRIPTS_DIR, "..", "env.mega.example");
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

before(() => {
  root = mkdtempSync(join(tmpdir(), "envsync-"));
});
after(() => {
  rmSync(root, { recursive: true, force: true });
});

test("sync writes target files and resolves ${common}", () => {
  write(
    ".env.mega",
    [
      "# >>> common",
      "SUPABASE_URL=https://x.supabase.co",
      "# >>> apps/desktop/.env",
      "VITE_SUPABASE_URL=${SUPABASE_URL}",
      "VITE_API_BASE_URL=http://127.0.0.1:8000",
    ].join("\n"),
  );

  const out = run(["sync"]);
  assert.match(out, /apps\/desktop\/\.env/);
  assert.match(out, /VITE_SUPABASE_URL/); // key is logged
  assert.doesNotMatch(out, /supabase\.co/); // value is NOT logged (§7)

  const written = read("apps/desktop/.env");
  assert.match(written, /VITE_SUPABASE_URL=https:\/\/x\.supabase\.co/);
});

test("sync warns about keys that exist in the target but not the mega", () => {
  write("packages/api/.env", "SOLUS_DATABASE_URL=old\nSOLUS_LEGACY=drop_me\n");
  write(".env.mega", "# >>> packages/api/.env\nSOLUS_DATABASE_URL=new\n");

  const out = run(["sync"]);
  assert.match(out, /SOLUS_LEGACY/);
  assert.match(out, /dropped/i);
  assert.match(read("packages/api/.env"), /SOLUS_DATABASE_URL=new/);
});

test("sync fails clearly when .env.mega is absent", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  const out = runExpectFail(["sync"]);
  assert.match(out, /env\.mega not found/i);
});

test("gather seeds .env.mega from existing files and round-trips via sync", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(
    "apps/web/.env",
    "export GOOGLE_SHEETS_SPREADSHEET_ID=sheet123\nGOOGLE_SHEETS_RANGE=WaitlistA:C\n",
  );
  write("packages/api/.env", 'SOLUS_DATABASE_URL="postgres://a b/c"\n');

  const out = run(["gather"]);
  assert.match(out, /apps\/web\/\.env/);
  const mega = read(".env.mega");
  assert.match(mega, /# >>> apps\/web\/\.env/);
  assert.match(mega, /GOOGLE_SHEETS_SPREADSHEET_ID=sheet123/);

  // The gathered mega must sync back to valid files.
  run(["sync"]);
  assert.match(read("apps/web/.env"), /GOOGLE_SHEETS_RANGE=WaitlistA:C/);
  assert.match(
    read("packages/api/.env"),
    /SOLUS_DATABASE_URL="postgres:\/\/a b\/c"/,
  );
});

test("gather ignores .aws.env — deploy vars are GitLab CI variables (SOLUSDEV-152)", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(".aws.env", "AWS_ACCOUNT=123\n");
  write("packages/api/.env", "SOLUS_DATABASE_URL=x\n");

  const out = run(["gather"]);
  assert.doesNotMatch(out, /\.aws\.env/);
  const mega = read(".env.mega");
  assert.doesNotMatch(mega, /# >>> \.aws\.env/);
  assert.doesNotMatch(mega, /AWS_ACCOUNT/);
});

test("gather includes the root .env (REDIS_URL & friends reach the mega)", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(".env", "REDIS_URL=redis://localhost:6379\nDB_USER=solus\n");

  const out = run(["gather"]);
  assert.match(out, /\.env/);
  const mega = read(".env.mega");
  assert.match(mega, /# >>> \.env\n/);
  assert.match(mega, /REDIS_URL=redis:\/\/localhost:6379/);
  assert.match(mega, /DB_USER=solus/);

  // Round-trip: sync regenerates the root .env from its mega block.
  write(".env", "STALE=1\n");
  run(["sync"]);
  assert.match(read(".env"), /REDIS_URL=redis:\/\/localhost:6379/);
  assert.doesNotMatch(read(".env"), /STALE/);
});

test("gather refuses to clobber an existing .env.mega without --force", () => {
  writeFileSync(
    join(root, ".env.mega"),
    "# >>> packages/api/.env\nSOLUS_DATABASE_URL=keep\n",
  );
  const out = runExpectFail(["gather"]);
  assert.match(out, /already exists/i);
  assert.match(read(".env.mega"), /SOLUS_DATABASE_URL=keep/); // untouched

  write("packages/api/.env", "SOLUS_DATABASE_URL=fresh\n");
  run(["gather", "--force"]); // now allowed
  assert.match(read(".env.mega"), /SOLUS_DATABASE_URL=fresh/);
});

test("sync refuses a path that escapes the repo root", () => {
  writeFileSync(join(root, ".env.mega"), "# >>> ../escape.env\nX=1\n");
  const out = runExpectFail(["sync"]);
  assert.match(out, /outside the repo/i);
  assert.equal(existsSync(resolve(root, "../escape.env")), false);
});

test("unknown subcommand fails with usage", () => {
  const out = runExpectFail(["frobnicate"]);
  assert.match(out, /unknown command/i);
});

// --- SOLUSDEV-152 WS-C: env.mega.example completeness ------------------------
// The committed template IS the onboarding checklist: cp → fill → env:sync must
// yield a boot-ready backend + desktop + web. These tests pin the template to
// the consuming code (config.py Settings, client.ts, waitlist route.js).

// Every SOLUS_* key the backend Settings consumes (core/config.py). Deliberately
// excludes SOLUS_STRIPE_SECRET_KEY: dead field, removed in SOLUSDEV-152.
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

const exampleTargets = () => {
  const targets = splitToTargets(readFileSync(EXAMPLE, "utf8"));
  return Object.fromEntries(targets.map((t) => [t.path, t.content]));
};
const keyNames = (content) => parseEnvFile(content).map((e) => e.key);

test("env.mega.example parses and declares every app target (no dead .aws.env)", () => {
  const byPath = exampleTargets();

  assert.equal(byPath[".aws.env"], undefined); // GitLab CI variables, not in-repo env
  for (const path of [
    "apps/desktop/.env",
    "apps/desktop/.env.claude",
    "apps/web/.env",
    "packages/api/.env",
    "packages/api/.env.claude",
  ]) {
    assert.ok(byPath[path], `missing block: # >>> ${path}`);
  }
});

test("env.mega.example api blocks carry every consumed SOLUS_* key", () => {
  const byPath = exampleTargets();
  for (const path of ["packages/api/.env", "packages/api/.env.claude"]) {
    const keys = new Set(keyNames(byPath[path]));
    for (const key of REQUIRED_API_KEYS) {
      assert.ok(keys.has(key), `${path} is missing ${key}`);
    }
    assert.ok(
      !keys.has("SOLUS_STRIPE_SECRET_KEY"),
      `${path} must not add SOLUS_STRIPE_SECRET_KEY`,
    );
  }
});

test("env.mega.example matches code semantics (no drifted defaults)", () => {
  const byPath = exampleTargets();

  // client.ts:113 falls back to http://localhost:8000/api/v1 — the template
  // value must keep the /api/v1 suffix or every API call 404s.
  for (const path of ["apps/desktop/.env", "apps/desktop/.env.claude"]) {
    assert.match(byPath[path], /VITE_API_BASE_URL=\S*\/api\/v1\b/);
  }

  for (const path of ["packages/api/.env", "packages/api/.env.claude"]) {
    // Schema is owned by Alembic migrations; create_all stays off.
    assert.match(byPath[path], /SOLUS_AUTO_CREATE_TABLES=false/);
    // api_version is a semver reported by /meta, not a route prefix.
    assert.match(byPath[path], /SOLUS_API_VERSION=0\.1\.0/);
  }
});

test("env.mega.example documents SOLUS_SECRETS_BACKEND but ships it commented", () => {
  // build_secret_store auto-selects a backend only when secrets_backend is
  // None (unset). pydantic-settings turns `SOLUS_SECRETS_BACKEND=` (blank)
  // into "", which is NOT None and silently disables auto-selection — so the
  // template must document the key without emitting it.
  const raw = readFileSync(EXAMPLE, "utf8");
  assert.match(raw, /SOLUS_SECRETS_BACKEND/);
  for (const path of ["packages/api/.env", "packages/api/.env.claude"]) {
    const keys = new Set(keyNames(exampleTargets()[path]));
    assert.ok(
      !keys.has("SOLUS_SECRETS_BACKEND"),
      `${path}: SOLUS_SECRETS_BACKEND must stay commented (blank breaks backend auto-selection)`,
    );
  }
});

test("env.mega.example web block covers the waitlist route env", () => {
  const keys = new Set(keyNames(exampleTargets()["apps/web/.env"]));
  for (const key of [
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_SERVICE_ACCOUNT_EMAIL",
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    "GOOGLE_SHEETS_RANGE",
  ]) {
    assert.ok(keys.has(key), `apps/web/.env block is missing ${key}`);
  }
});

test("env.mega.example documents the SecretStore provisioning step for LLM keys", () => {
  const raw = readFileSync(EXAMPLE, "utf8");
  // providers.py reads these from the SecretStore — they are NOT env vars.
  for (const ref of ["anthropic_api_key", "openai_api_key", "google_api_key"]) {
    assert.ok(raw.includes(ref), `template must name SecretStore ref ${ref}`);
  }
  assert.match(raw, /Secrets Manager/i);
});

test("env.mega.example holds no real-looking secret values", () => {
  const byPath = exampleTargets();
  for (const [path, content] of Object.entries(byPath)) {
    for (const { key, value } of parseEnvFile(content)) {
      if (!/(KEY|SECRET|TOKEN|PRIVATE)/.test(key)) continue;
      assert.ok(
        value === "" || /CHANGE_ME|changeme|\$\{/.test(value),
        `${path}: ${key} must be blank or an obvious placeholder`,
      );
    }
  }
});
