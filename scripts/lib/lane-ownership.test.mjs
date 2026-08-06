// SOLUSDEV-222 (CTR-07) — the lane-ownership rules, asserted executably.
//
// The acceptance criterion this file encodes: the check FAILS a deliberate
// cross-lane edit, PASSES a legitimate in-lane one, and never blocks LANE 0.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  SHARED_OWNER,
  findViolations,
  formatViolations,
  knownLanes,
  laneFromBranch,
  ownerOf,
  parseCodeowners,
  unknownOwners,
} from "./lane-ownership.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const realRules = () => parseCodeowners(readFileSync(resolve(ROOT, "CODEOWNERS"), "utf8"));

const FIXTURE = `
*                                            @shared
/packages/api/src/solus_api/agent/           @lane-sol
/packages/api/src/solus_api/agent/perf.py    @lane-systems
/apps/desktop/src/renderer/src/widgets/parts/ @lane-workspace
`;

// ── branch -> lane ───────────────────────────────────────────────────────────

test("derives the lane slug from a lane branch name", () => {
  assert.equal(laneFromBranch("SOLUSDEV-214-lane-workspace"), "workspace");
  assert.equal(laneFromBranch("SOLUSDEV-215-lane-tool-understanding"), "tool-understanding");
});

test("returns null for a branch that belongs to no lane", () => {
  // The bootstrapping guarantee: LANE 0's own branch and every ordinary ticket
  // branch must be skipped, not blocked.
  assert.equal(laneFromBranch("SOLUSDEV-216-CTR"), null);
  assert.equal(laneFromBranch("SOLUSDEV-34-implement-onshape-integration"), null);
  assert.equal(laneFromBranch("main"), null);
  assert.equal(laneFromBranch(""), null);
  assert.equal(laneFromBranch(undefined), null);
});

test("a lane slug may contain hyphens, so the suffix is taken whole", () => {
  // There is no way to tell "workspace-wip" from a legitimately hyphenated slug
  // like "tool-understanding", and no reason to try — an unrecognised slug is
  // caught by knownLanes() below, with a message that says so.
  assert.equal(laneFromBranch("SOLUSDEV-9-lane-workspace-wip"), "workspace-wip");
});

test("knownLanes lists exactly the lanes CODEOWNERS assigns paths to", () => {
  const lanes = knownLanes(parseCodeowners(FIXTURE));
  assert.deepEqual([...lanes].sort(), ["sol", "systems", "workspace"]);
});

test("a branch naming a lane CODEOWNERS does not know is an error, not a pass", () => {
  // Without this, a typo'd branch yields a lane owning nothing, so every path
  // is a violation and the message blames the diff instead of the branch name.
  const lanes = knownLanes(parseCodeowners(FIXTURE));
  assert.ok(!lanes.has("workspace-wip"));
  assert.ok(lanes.has("workspace"));
});

// ── ownership resolution ─────────────────────────────────────────────────────

test("an unclaimed path falls through to the shared owner", () => {
  const rules = parseCodeowners(FIXTURE);
  assert.equal(ownerOf("packages/shared-types/widget.ts", rules), SHARED_OWNER);
});

test("a directory rule owns everything beneath it", () => {
  const rules = parseCodeowners(FIXTURE);
  assert.equal(ownerOf("packages/api/src/solus_api/agent/runtime.py", rules), "@lane-sol");
  assert.equal(ownerOf("packages/api/src/solus_api/agent/tools/registry.py", rules), "@lane-sol");
});

test("a later, more specific rule reassigns one file out of a lane's directory", () => {
  // This is how agent/perf.py belongs to LANE E while agent/ belongs to LANE C.
  const rules = parseCodeowners(FIXTURE);
  assert.equal(ownerOf("packages/api/src/solus_api/agent/perf.py", rules), "@lane-systems");
});

test("a directory rule does not match a sibling with the same prefix", () => {
  const rules = parseCodeowners("*  @shared\n/apps/web/  @lane-production\n");
  assert.equal(ownerOf("apps/website/index.ts", rules), SHARED_OWNER);
});

// ── the acceptance criteria ──────────────────────────────────────────────────

test("fails a deliberate cross-lane edit", () => {
  const rules = parseCodeowners(FIXTURE);
  const violations = findViolations(
    ["apps/desktop/src/renderer/src/widgets/parts/PartsWidget.tsx", "packages/api/src/solus_api/agent/runtime.py"],
    "workspace",
    rules,
  );
  assert.equal(violations.length, 1);
  assert.equal(violations[0].path, "packages/api/src/solus_api/agent/runtime.py");
  assert.equal(violations[0].owner, "@lane-sol");
  assert.match(formatViolations(violations, "workspace"), /BLOCKED/);
});

test("passes a legitimate in-lane edit", () => {
  const rules = parseCodeowners(FIXTURE);
  const violations = findViolations(
    [
      "apps/desktop/src/renderer/src/widgets/parts/PartsWidget.tsx",
      "apps/desktop/src/renderer/src/widgets/parts/widget.manifest.ts",
    ],
    "workspace",
    rules,
  );
  assert.deepEqual(violations, []);
});

test("a lane touching a shared path is a violation, not a pass", () => {
  // Shared paths are LANE 0's; the fix is a contract ticket, not a direct edit.
  const rules = parseCodeowners(FIXTURE);
  const violations = findViolations(["packages/shared-types/widget.ts"], "workspace", rules);
  assert.equal(violations.length, 1);
  assert.equal(violations[0].owner, SHARED_OWNER);
});

test("deleting another lane's file counts as a cross-lane edit", () => {
  const rules = parseCodeowners(FIXTURE);
  const violations = findViolations(["packages/api/src/solus_api/agent/perf.py"], "sol", rules);
  assert.equal(violations.length, 1);
  assert.equal(violations[0].owner, "@lane-systems");
});

// ── parser strictness ────────────────────────────────────────────────────────

test("rejects a path with two owners", () => {
  assert.throws(
    () => parseCodeowners("*  @shared\n/apps/  @lane-a @lane-b\n"),
    /exactly one/,
  );
});

test("rejects an unsupported glob rather than silently matching nothing", () => {
  assert.throws(() => parseCodeowners("*  @shared\n/apps/**/*.ts  @lane-a\n"), /glob/);
});

test("rejects a rule with no owner", () => {
  assert.throws(() => parseCodeowners("/apps/\n"), /no owner/);
});

test("ignores comments and blank lines", () => {
  const rules = parseCodeowners("# a comment\n\n*  @shared  # trailing\n");
  assert.equal(rules.length, 1);
});

// ── the real CODEOWNERS ──────────────────────────────────────────────────────

test("the committed CODEOWNERS parses and has no typo'd owner handles", () => {
  assert.deepEqual(unknownOwners(realRules()), []);
});

test("every tracked top-level directory resolves to an owner", () => {
  // "No unowned path" is guaranteed structurally by the `*` default; this
  // asserts the default is actually present and first.
  const rules = realRules();
  assert.equal(rules[0].pattern, "*");
  for (const path of ["packages/api/src/solus_api/main.py", "brand/logo.svg", "Makefile"]) {
    assert.ok(ownerOf(path, rules).startsWith("@"), `${path} has no owner`);
  }
});

test("no two rules in the committed CODEOWNERS claim the same pattern", () => {
  // Double-owned paths are the failure this file exists to prevent; an
  // accidental duplicate line would silently let the later one win.
  const seen = new Map();
  for (const rule of realRules()) {
    assert.ok(!seen.has(rule.pattern), `${rule.pattern} appears on lines ${seen.get(rule.pattern)} and ${rule.line}`);
    seen.set(rule.pattern, rule.line);
  }
});
