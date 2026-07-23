// SOLUSDEV-147 / SOLUSDEV-164 — unit tests for the flat .env.mega parser/
// renderer (pure, no FS). Run: node --test scripts/lib/env-mega.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseMega,
  resolveMega,
  parseEnvFile,
  serializeEntries,
  mergeEnvFiles,
  renderMega,
  diffKeys,
} from "./env-mega.mjs";

// ---------------------------------------------------------------------------
// parseMega — flat structure
// ---------------------------------------------------------------------------
test("parseMega reads a flat KEY=VALUE list in order", () => {
  const mega = [
    "# a file-level comment, ignored",
    "",
    "VITE_API_BASE_URL=http://127.0.0.1:8000",
    "SOLUS_DATABASE_URL=postgres://a/b",
  ].join("\n");

  const { entries } = parseMega(mega);
  assert.deepEqual(
    entries.map((e) => e.key),
    ["VITE_API_BASE_URL", "SOLUS_DATABASE_URL"],
  );
  assert.equal(entries[1].value, "postgres://a/b");
});

test("parseMega treats a legacy `# >>> path` header as an ignored comment", () => {
  const { entries } = parseMega(
    "# >>> apps/desktop/.env\nVITE_X=1\n# >>> common\nSHARED=2\n",
  );
  assert.deepEqual(
    entries.map((e) => e.key),
    ["VITE_X", "SHARED"],
  );
});

test("parseMega de-duplicates keys, last value winning, keeping first-seen order", () => {
  const { entries } = parseMega("A=1\nB=2\nA=3\n");
  assert.deepEqual(entries, [
    { key: "A", value: "3" },
    { key: "B", value: "2" },
  ]);
});

test("parseMega throws on an invalid key name", () => {
  assert.throws(() => parseMega("1BAD=x\n"), /invalid/i);
});

test("parseMega throws on a non-comment line with no '='", () => {
  assert.throws(() => parseMega("nonsense line\n"), /KEY=VALUE/);
});

// ---------------------------------------------------------------------------
// resolveMega — interpolation + emission (every key is emitted)
// ---------------------------------------------------------------------------
test("resolveMega resolves ${VAR} from an earlier key and emits both", () => {
  const entries = resolveMega(
    [
      "SUPABASE_URL=https://x.supabase.co",
      "VITE_SUPABASE_URL=${SUPABASE_URL}",
    ].join("\n"),
  );
  assert.deepEqual(entries, [
    { key: "SUPABASE_URL", value: "https://x.supabase.co" },
    { key: "VITE_SUPABASE_URL", value: "https://x.supabase.co" },
  ]);
});

test("resolveMega resolves a chain of references", () => {
  const entries = resolveMega(
    "AWS_ACCOUNT=1234\nECR_URI=${AWS_ACCOUNT}.dkr.ecr\n",
  );
  assert.equal(entries.find((e) => e.key === "ECR_URI").value, "1234.dkr.ecr");
});

test("resolveMega throws on an unresolved reference, naming the var", () => {
  assert.throws(() => resolveMega("A=${MISSING}\n"), /MISSING/);
});

test("resolveMega treats single-quoted values as literal (no interpolation)", () => {
  const [t] = resolveMega("PASS='literal_${NOPE}_kept'\n");
  assert.equal(t.value, "literal_${NOPE}_kept");
});

test("resolveMega strips inline comments from bare values but keeps '#' with no leading space", () => {
  const entries = resolveMega(
    ["URL=http://h:8000    # trailing comment", "FRAG=http://h/#section"].join(
      "\n",
    ),
  );
  assert.equal(entries[0].value, "http://h:8000");
  assert.equal(entries[1].value, "http://h/#section");
});

test("resolveMega keeps '#' inside a quoted value", () => {
  const [t] = resolveMega('KEY="a #b"\n');
  assert.equal(t.value, "a #b");
});

// ---------------------------------------------------------------------------
// parseEnvFile — for gather (reading existing files)
// ---------------------------------------------------------------------------
test("parseEnvFile reads KEY=VALUE, ignoring comments and blanks", () => {
  const entries = parseEnvFile("# c\n\nA=1\nB=two words\n");
  assert.deepEqual(entries, [
    { key: "A", value: "1" },
    { key: "B", value: "two words" },
  ]);
});

test("parseEnvFile strips an optional leading 'export'", () => {
  assert.deepEqual(parseEnvFile("export AWS_REGION=us-east-1\n"), [
    { key: "AWS_REGION", value: "us-east-1" },
  ]);
});

test("parseEnvFile keeps '=' inside the value", () => {
  assert.deepEqual(parseEnvFile("DSN=a=b=c\n"), [
    { key: "DSN", value: "a=b=c" },
  ]);
});

test("parseEnvFile unwraps quoted values", () => {
  assert.deepEqual(parseEnvFile('K="a #b"\n'), [{ key: "K", value: "a #b" }]);
});

// ---------------------------------------------------------------------------
// serializeEntries — writing target files safely
// ---------------------------------------------------------------------------
test("serializeEntries leaves simple values bare and quotes risky ones", () => {
  const out = serializeEntries([
    { key: "A", value: "http://127.0.0.1:8000" },
    { key: "B", value: "has space" },
    { key: "C", value: "" },
  ]);
  assert.match(out, /^A=http:\/\/127\.0\.0\.1:8000$/m);
  assert.match(out, /^B="has space"$/m);
  assert.match(out, /^C=$/m);
});

test("serializeEntries escapes quotes and backslashes", () => {
  const out = serializeEntries([{ key: "K", value: 'a"b\\c' }]);
  assert.match(out, /^K="a\\"b\\\\c"$/m);
});

// ---------------------------------------------------------------------------
// mergeEnvFiles — gather de-dup + conflict detection
// ---------------------------------------------------------------------------
test("mergeEnvFiles keeps the first occurrence and flags divergent values", () => {
  const { entries, conflicts } = mergeEnvFiles([
    {
      path: ".env",
      entries: [
        { key: "A", value: "1" },
        { key: "B", value: "x" },
      ],
    },
    {
      path: "packages/api/.env",
      entries: [
        { key: "A", value: "1" },
        { key: "B", value: "y" },
        { key: "C", value: "z" },
      ],
    },
  ]);
  assert.deepEqual(
    entries.map((e) => e.key),
    ["A", "B", "C"],
  );
  assert.equal(entries.find((e) => e.key === "B").value, "x"); // first wins
  assert.deepEqual(conflicts, ["B"]);
});

// ---------------------------------------------------------------------------
// renderMega — for gather output; must round-trip through resolveMega
// ---------------------------------------------------------------------------
test("renderMega emits a flat body that round-trips through resolveMega", () => {
  const entries = [
    { key: "AWS_REGION", value: "us-east-1" },
    { key: "VITE_API_BASE_URL", value: "http://h:8000" },
  ];
  const mega = renderMega(entries);
  assert.doesNotMatch(mega, /# >>>/); // no legacy routing headers
  const round = resolveMega(mega);
  assert.deepEqual(round, entries);
});

test("renderMega round-trips a value containing '$' without interpolating it", () => {
  const mega = renderMega([{ key: "P", value: "a${b}c" }]);
  assert.match(mega, /P="a\\\$\{b\}c"/); // escaped $ in the mega
  assert.equal(resolveMega(mega)[0].value, "a${b}c"); // survived literally
});

test("renderMega round-trips a value with both '$' and a single quote (no data loss)", () => {
  const secret = "p$a'ss${X}"; // has $, a literal ', and a ${...}
  assert.equal(
    resolveMega(renderMega([{ key: "PW", value: secret }]))[0].value,
    secret,
  );
});

// ---------------------------------------------------------------------------
// diffKeys — drift/loss guard for sync
// ---------------------------------------------------------------------------
test("diffKeys reports keys present in the target but missing from the mega", () => {
  assert.deepEqual(diffKeys(["A", "B", "C"], ["A", "C"]), ["B"]);
});

test("diffKeys returns [] when the mega covers every existing key", () => {
  assert.deepEqual(diffKeys(["A"], ["A", "B"]), []);
});
