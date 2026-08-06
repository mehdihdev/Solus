// SOLUSDEV-222 (CTR-07) — pure lane-ownership logic. No filesystem, no git, no
// process access, so it is fully unit-testable; the CLI wrapper
// (scripts/check-lane-ownership.mjs) does the I/O.
//
// CODEOWNERS is the SINGLE source of truth. There is deliberately no second
// lane -> globs map: two hand-maintained copies of one mapping is exactly the
// drift this ticket exists to prevent.
//
// The lane a branch belongs to is derived from its NAME:
//   branch SOLUSDEV-214-lane-workspace  ->  lane slug "workspace"  ->  @lane-workspace
// A branch with no `-lane-<slug>` suffix belongs to no lane and is not checked —
// that is what keeps LANE 0 and ordinary ticket branches from being blocked.

/** Owner handle for paths no feature lane owns (LANE 0 / cross-cutting). */
export const SHARED_OWNER = "@shared";

const LANE_BRANCH_RE = /-lane-([a-z0-9][a-z0-9-]*)$/;
const OWNER_RE = /^@[a-z0-9][a-z0-9-]*$/;

/**
 * The lane slug a branch belongs to, or null if it belongs to none.
 *
 * Returning null (rather than throwing) is load-bearing: the caller treats it
 * as "not a lane branch, skip the check". Ordinary ticket branches and LANE 0's
 * own branch must never fail this job.
 */
export function laneFromBranch(branch) {
  const match = LANE_BRANCH_RE.exec((branch ?? "").trim());
  return match ? match[1] : null;
}

/**
 * Parse CODEOWNERS into ordered rules.
 *
 * Only the three pattern shapes this repo's CODEOWNERS actually uses are
 * supported — `*`, a `/dir/` prefix, and an exact `/path/to/file`. Anything else
 * THROWS rather than being silently ignored, because a pattern that quietly
 * matches nothing would report a cross-lane edit as compliant.
 */
export function parseCodeowners(text) {
  const rules = [];
  const lines = String(text).split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].replace(/#.*$/, "").trim();
    if (!line) continue;
    const [pattern, ...owners] = line.split(/\s+/);
    if (owners.length === 0) {
      throw new Error(`CODEOWNERS line ${i + 1}: "${pattern}" has no owner`);
    }
    for (const owner of owners) {
      if (!OWNER_RE.test(owner)) {
        throw new Error(`CODEOWNERS line ${i + 1}: "${owner}" is not a valid owner handle`);
      }
    }
    if (owners.length > 1) {
      // One path, one lane — the whole premise. Two owners means two lanes may
      // edit it, which is the collision this file prevents.
      throw new Error(`CODEOWNERS line ${i + 1}: "${pattern}" has ${owners.length} owners; a path must have exactly one`);
    }
    rules.push({ pattern, owner: owners[0], line: i + 1, match: compile(pattern, i + 1) });
  }
  if (rules.length === 0) throw new Error("CODEOWNERS has no rules");
  return rules;
}

function compile(pattern, lineNo) {
  if (pattern === "*") return () => true;
  if (!pattern.startsWith("/")) {
    throw new Error(`CODEOWNERS line ${lineNo}: "${pattern}" must be "*" or start with "/"`);
  }
  if (/[*?[\]]/.test(pattern)) {
    throw new Error(`CODEOWNERS line ${lineNo}: "${pattern}" uses a glob; only "*", "/dir/" and exact "/path" are supported`);
  }
  const body = pattern.slice(1);
  if (body.endsWith("/")) return (path) => path === body.slice(0, -1) || path.startsWith(body);
  return (path) => path === body;
}

/**
 * The owner of one repo-relative path. LAST matching rule wins (GitLab/GitHub
 * semantics), which is what lets a single file inside a lane's directory be
 * reassigned by a more-specific line placed after it.
 */
export function ownerOf(path, rules) {
  let owner = SHARED_OWNER;
  for (const rule of rules) if (rule.match(path)) owner = rule.owner;
  return owner;
}

/**
 * Paths in `changedPaths` that the given lane does not own.
 *
 * A DELETED file still counts: removing another lane's file is as much a
 * cross-lane edit as changing it, and git reports both the same way.
 */
export function findViolations(changedPaths, laneSlug, rules) {
  const expected = `@lane-${laneSlug}`;
  return changedPaths
    .map((path) => ({ path, owner: ownerOf(path, rules) }))
    .filter((entry) => entry.owner !== expected);
}

/**
 * The lane slugs CODEOWNERS actually assigns paths to.
 *
 * A branch whose slug is not in here is a NAMING error, and saying so is much
 * clearer than the alternative: a lane that owns nothing, so every changed path
 * reads as a cross-lane violation and the message blames the diff.
 */
export function knownLanes(rules) {
  return new Set(
    rules
      .map((rule) => rule.owner)
      .filter((owner) => owner.startsWith("@lane-"))
      .map((owner) => owner.slice("@lane-".length)),
  );
}

/**
 * Every rule whose owner is not @shared and not a well-formed lane handle.
 * Guards against a typo'd handle silently creating a lane nothing can match.
 */
export function unknownOwners(rules) {
  return [...new Set(rules.map((r) => r.owner))].filter(
    (owner) => owner !== SHARED_OWNER && !owner.startsWith("@lane-"),
  );
}

/** Human-readable report. Returned rather than printed so the lib stays pure. */
export function formatViolations(violations, laneSlug) {
  const lines = [
    `[lane-ownership] BLOCKED: branch is lane "${laneSlug}" (@lane-${laneSlug}) but ${violations.length} changed path(s) belong to another owner:`,
    "",
    ...violations.map((v) => `  ${v.path}  ->  ${v.owner}`),
    "",
    "A lane never edits outside its owned paths (docs/WORKTREES.md).",
    "If the change is genuinely needed, open a LANE 0 contract ticket instead of",
    "editing across the boundary. A human may set LANE_OWNERSHIP_OVERRIDE=1 for a",
    "one-off; agents never do.",
  ];
  return lines.join("\n");
}
