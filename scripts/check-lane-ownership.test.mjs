// SOLUSDEV-222 (CTR-07) — CLI-level tests for the lane-ownership guard.
//
// The rules themselves are unit-tested in lib/lane-ownership.test.mjs; this file
// asserts the three exit codes CI actually depends on, against the REAL
// committed CODEOWNERS.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = resolve(dirname(fileURLToPath(import.meta.url)), "check-lane-ownership.mjs");

function run(args, env = {}) {
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: "utf8",
    // Blank the CI variables so a real pipeline run cannot leak into the test.
    env: {
      ...process.env,
      CI_MERGE_REQUEST_SOURCE_BRANCH_NAME: "",
      CI_COMMIT_BRANCH: "",
      LANE_OWNERSHIP_OVERRIDE: "",
      ...env,
    },
  });
  return { code: result.status, out: result.stdout + result.stderr };
}

test("fails a deliberate cross-lane edit", () => {
  const { code, out } = run([
    "--branch",
    "SOLUSDEV-214-lane-workspace",
    "apps/desktop/src/renderer/src/features/workspace/Canvas.tsx",
    "packages/api/src/solus_api/agent/runtime.py",
  ]);
  assert.equal(code, 1);
  assert.match(out, /BLOCKED/);
  assert.match(out, /agent\/runtime\.py\s+->\s+@lane-sol/);
});

test("passes a legitimate in-lane edit", () => {
  const { code, out } = run([
    "--branch",
    "SOLUSDEV-214-lane-workspace",
    "apps/desktop/src/renderer/src/features/workspace/Canvas.tsx",
    "apps/desktop/src/renderer/src/widgets/impact/widget.manifest.ts",
  ]);
  assert.equal(code, 0);
  assert.match(out, /OK/);
});

test("does not block LANE 0 or any ordinary ticket branch", () => {
  // The bootstrapping requirement, asserted on the branch this ticket is built on.
  for (const branch of ["SOLUSDEV-216-CTR", "SOLUSDEV-34-implement-onshape-integration"]) {
    const { code, out } = run(["--branch", branch, "packages/shared-types/widget.ts", "CODEOWNERS"]);
    assert.equal(code, 0, `${branch} should be skipped`);
    assert.match(out, /not a lane branch/);
  }
});

test("blames the branch name when the lane is unknown", () => {
  const { code, out } = run(["--branch", "SOLUSDEV-9-lane-typo", "Makefile"]);
  assert.equal(code, 1);
  assert.match(out, /owns no path in CODEOWNERS/);
  assert.match(out, /Known lanes:/);
});

test("a human override still prints the violations", () => {
  const { code, out } = run(
    ["--branch", "SOLUSDEV-214-lane-workspace", "packages/api/src/solus_api/agent/runtime.py"],
    { LANE_OWNERSHIP_OVERRIDE: "1" },
  );
  assert.equal(code, 0);
  assert.match(out, /BLOCKED/);
  assert.match(out, /set by a human/);
});
