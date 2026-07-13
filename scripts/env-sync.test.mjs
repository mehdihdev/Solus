// SOLUSDEV-147 — integration tests for the env CLI against a temp tree.
// Exercises sync/gather I/O without ever touching the real .env files.
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

const CLI = resolve(dirname(fileURLToPath(import.meta.url)), "env-sync.mjs");
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
  write(".aws.env", "export AWS_REGION=us-east-1\nAWS_ACCOUNT=123\n");
  write("packages/api/.env", 'SOLUS_DATABASE_URL="postgres://a b/c"\n');

  const out = run(["gather"]);
  assert.match(out, /\.aws\.env/);
  const mega = read(".env.mega");
  assert.match(mega, /# >>> \.aws\.env/);
  assert.match(mega, /AWS_REGION=us-east-1/);

  // The gathered mega must sync back to valid files.
  run(["sync"]);
  assert.match(read(".aws.env"), /AWS_ACCOUNT=123/);
  assert.match(
    read("packages/api/.env"),
    /SOLUS_DATABASE_URL="postgres:\/\/a b\/c"/,
  );
});

test("gather includes the root .env (REDIS_URL & friends reach the mega)", () => {
  rmSync(join(root, ".env.mega"), { force: true });
  write(".env", "REDIS_URL=redis://localhost:6379\nDB_USER=solus\n");
  write(".aws.env", "AWS_ACCOUNT=123\n");

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
  writeFileSync(join(root, ".env.mega"), "# >>> .aws.env\nAWS_ACCOUNT=keep\n");
  const out = runExpectFail(["gather"]);
  assert.match(out, /already exists/i);
  assert.match(read(".env.mega"), /AWS_ACCOUNT=keep/); // untouched

  write(".aws.env", "AWS_ACCOUNT=fresh\n");
  run(["gather", "--force"]); // now allowed
  assert.match(read(".env.mega"), /AWS_ACCOUNT=fresh/);
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
