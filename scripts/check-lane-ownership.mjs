#!/usr/bin/env node
// SOLUSDEV-222 (CTR-07) — CI guard: a lane branch may only change paths its lane
// owns in CODEOWNERS. See docs/WORKTREES.md for the protocol.
//
//   node scripts/check-lane-ownership.mjs                  # derive branch + diff from CI/git
//   node scripts/check-lane-ownership.mjs --branch X a b    # explicit branch + paths (local)
//
// Exit 0 = compliant, or not a lane branch at all. Exit 1 = cross-lane edit.
//
// This wrapper is deliberately thin: every rule lives in scripts/lib/lane-ownership.mjs
// and is unit-tested there, because a guard nobody can test is a guard nobody trusts.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  findViolations,
  formatViolations,
  knownLanes,
  laneFromBranch,
  parseCodeowners,
} from "./lib/lane-ownership.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function git(...args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

function currentBranch() {
  // MR pipelines run on a detached ref, so the source branch only exists as a
  // CI variable — `git rev-parse HEAD` there would report "HEAD" and skip.
  return (
    process.env.CI_MERGE_REQUEST_SOURCE_BRANCH_NAME ||
    process.env.CI_COMMIT_BRANCH ||
    git("rev-parse", "--abbrev-ref", "HEAD")
  );
}

function changedPaths() {
  const target = process.env.CI_MERGE_REQUEST_TARGET_BRANCH_NAME || "main";
  // Three-dot: everything on this branch since it diverged, not what main did
  // meanwhile — otherwise a lane fails for another lane's merged work.
  const base = git("merge-base", `origin/${target}`, "HEAD");
  return git("diff", "--name-only", base, "HEAD").split("\n").filter(Boolean);
}

function main(argv) {
  const flag = argv.indexOf("--branch");
  const branch = flag === -1 ? currentBranch() : argv[flag + 1];
  const explicit = flag === -1 ? null : argv.slice(flag + 2);

  const lane = laneFromBranch(branch);
  if (lane === null) {
    // Ordinary ticket branches and LANE 0's own branch belong to no lane. This
    // is the bootstrapping guarantee: the check can never block a contract ticket.
    console.log(`[lane-ownership] "${branch}" is not a lane branch — skipped.`);
    return 0;
  }

  const rules = parseCodeowners(readFileSync(resolve(ROOT, "CODEOWNERS"), "utf8"));
  const lanes = knownLanes(rules);
  if (!lanes.has(lane)) {
    console.error(
      `[lane-ownership] BLOCKED: branch "${branch}" names lane "${lane}", which owns no path in CODEOWNERS.\n` +
        `Known lanes: ${[...lanes].sort().join(", ")}\n` +
        `Branch names are SOLUSDEV-<epic#>-lane-<slug> (docs/WORKTREES.md).`,
    );
    return 1;
  }

  const paths = explicit && explicit.length ? explicit : changedPaths();
  if (paths.length === 0) {
    console.log("[lane-ownership] no changed paths — nothing to check.");
    return 0;
  }

  const violations = findViolations(paths, lane, rules);
  if (violations.length === 0) {
    console.log(`[lane-ownership] OK — ${paths.length} changed path(s), all owned by @lane-${lane}.`);
    return 0;
  }

  console.error(formatViolations(violations, lane));
  if (process.env.LANE_OWNERSHIP_OVERRIDE === "1") {
    // A human escape hatch, and it stays LOUD: the violations are printed above
    // either way, so an override never reads as a clean pass in the CI log.
    console.error("\n[lane-ownership] LANE_OWNERSHIP_OVERRIDE=1 set by a human — allowed.");
    return 0;
  }
  return 1;
}

process.exit(main(process.argv.slice(2)));
