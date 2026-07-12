// SOLUSDEV-147 — unit tests for the .env.mega parser/renderer (pure, no FS).
// Run: node --test scripts/lib/env-mega.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseMega,
  splitToTargets,
  parseEnvFile,
  serializeEntries,
  renderMega,
  diffKeys,
} from "./env-mega.mjs";

// ---------------------------------------------------------------------------
// parseMega — structure
// ---------------------------------------------------------------------------
test("parseMega groups KEY=VALUE lines under their >>> header", () => {
  const mega = [
    "# a file-level comment, ignored",
    "",
    "# >>> apps/desktop/.env",
    "VITE_API_BASE_URL=http://127.0.0.1:8000",
    "VITE_SUPABASE_URL=https://x.supabase.co",
    "",
    "# >>> packages/api/.env",
    "SOLUS_DATABASE_URL=postgres://a/b",
  ].join("\n");

  const { blocks } = parseMega(mega);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].path, "apps/desktop/.env");
  assert.equal(blocks[0].isCommon, false);
  assert.deepEqual(
    blocks[0].entries.map((e) => e.key),
    ["VITE_API_BASE_URL", "VITE_SUPABASE_URL"],
  );
  assert.equal(blocks[1].entries[0].value, "postgres://a/b");
});

test("parseMega marks the common block and keeps its order", () => {
  const { blocks } = parseMega("# >>> common\nA=1\nB=2\n");
  assert.equal(blocks[0].isCommon, true);
  assert.equal(blocks[0].path, "common");
});

test("parseMega throws when a KEY=VALUE appears before any header", () => {
  assert.throws(() => parseMega("STRAY=1\n# >>> .env\nA=2\n"), /before any/i);
});

test("parseMega throws on an invalid key name", () => {
  assert.throws(() => parseMega("# >>> .env\n1BAD=x\n"), /invalid/i);
});

test("parseMega throws on a non-comment line with no '='", () => {
  assert.throws(() => parseMega("# >>> .env\nnonsense line\n"), /KEY=VALUE/);
});

// ---------------------------------------------------------------------------
// splitToTargets — interpolation + emission
// ---------------------------------------------------------------------------
test("splitToTargets resolves ${VAR} from the common block", () => {
  const mega = [
    "# >>> common",
    "SUPABASE_URL=https://x.supabase.co",
    "# >>> apps/desktop/.env",
    "VITE_SUPABASE_URL=${SUPABASE_URL}",
  ].join("\n");

  const targets = splitToTargets(mega);
  assert.equal(targets.length, 1); // common is not emitted
  assert.equal(targets[0].path, "apps/desktop/.env");
  assert.equal(
    targets[0].content.trim(),
    "VITE_SUPABASE_URL=https://x.supabase.co",
  );
});

test("splitToTargets resolves an earlier key within the same block", () => {
  const mega = [
    "# >>> .aws.env",
    "AWS_ACCOUNT=1234",
    "ECR_URI=${AWS_ACCOUNT}.dkr.ecr",
  ].join("\n");
  const [t] = splitToTargets(mega);
  assert.match(t.content, /ECR_URI=1234\.dkr\.ecr/);
});

test("splitToTargets throws on an unresolved reference, naming the var", () => {
  const mega = "# >>> .env\nA=${MISSING}\n";
  assert.throws(() => splitToTargets(mega), /MISSING/);
});

test("splitToTargets treats single-quoted values as literal (no interpolation)", () => {
  const mega = "# >>> .env\nPASS='literal_${NOPE}_kept'\n";
  const [t] = splitToTargets(mega);
  assert.match(t.content, /PASS=.*literal_\$\{NOPE\}_kept/);
});

test("splitToTargets strips inline comments from bare values but keeps '#' with no leading space", () => {
  const mega = [
    "# >>> .env",
    "URL=http://h:8000    # trailing comment",
    "FRAG=http://h/#section",
  ].join("\n");
  const [t] = splitToTargets(mega);
  assert.match(t.content, /URL=http:\/\/h:8000\n/); // trailing comment stripped
  // '#' with no leading space is kept in the value (quoted for safe re-parsing).
  assert.match(t.content, /FRAG="http:\/\/h\/#section"/);
});

test("splitToTargets keeps '#' inside a quoted value", () => {
  const mega = '# >>> .env\nKEY="a #b"\n';
  const [t] = splitToTargets(mega);
  assert.match(t.content, /KEY="a #b"/);
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
  const entries = parseEnvFile("export AWS_REGION=us-east-1\n");
  assert.deepEqual(entries, [{ key: "AWS_REGION", value: "us-east-1" }]);
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
// renderMega — for gather output; must round-trip through splitToTargets
// ---------------------------------------------------------------------------
test("renderMega emits one block per file with headers, round-tripping values", () => {
  const files = [
    { path: ".aws.env", entries: [{ key: "AWS_REGION", value: "us-east-1" }] },
    {
      path: "apps/desktop/.env",
      entries: [{ key: "VITE_API_BASE_URL", value: "http://h:8000" }],
    },
  ];
  const mega = renderMega(files);
  assert.match(mega, /# >>> \.aws\.env/);
  assert.match(mega, /# >>> apps\/desktop\/\.env/);

  const targets = splitToTargets(mega);
  assert.equal(targets.length, 2);
  assert.match(targets[0].content, /AWS_REGION=us-east-1/);
});

test("renderMega round-trips a value containing '$' without interpolating it", () => {
  const files = [{ path: ".env", entries: [{ key: "P", value: "a${b}c" }] }];
  const mega = renderMega(files);
  assert.match(mega, /P="a\\\$\{b\}c"/); // escaped $ in the mega
  const [t] = splitToTargets(mega);
  assert.match(t.content, /P=.*a\$\{b\}c/); // survived literally
});

test("renderMega round-trips a value with both '$' and a single quote (no data loss)", () => {
  const secret = "p$a'ss${X}"; // has $, a literal ', and a ${...}
  const files = [{ path: ".env", entries: [{ key: "PW", value: secret }] }];
  const [t] = splitToTargets(renderMega(files));
  // The target value must equal the original secret byte-for-byte.
  const line = t.content.split("\n").find((l) => l.startsWith("PW="));
  const written = line
    .slice("PW=".length)
    .replace(/^"|"$/g, "")
    .replace(/\\(.)/g, "$1");
  assert.equal(written, secret);
});

// ---------------------------------------------------------------------------
// diffKeys — drift/loss guard for sync
// ---------------------------------------------------------------------------
test("diffKeys reports keys present in the target but missing from the mega", () => {
  const dropped = diffKeys(["A", "B", "C"], ["A", "C"]);
  assert.deepEqual(dropped, ["B"]);
});

test("diffKeys returns [] when the mega covers every existing key", () => {
  assert.deepEqual(diffKeys(["A"], ["A", "B"]), []);
});
