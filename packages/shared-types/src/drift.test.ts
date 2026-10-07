// SOLUSDEV-216 — the drift guard, closed.
//
// Code review found the original guard did not catch an ADDED field: `satisfies`
// does excess-property checking only on FRESH OBJECT LITERALS, and a fixture
// imported from `.json` is a variable. Verified — adding an undeclared field to
// a fixture left `tsc` silent while renaming a required one errored. "Add a
// field" is the change six lanes will make most often.
//
// The loop is now closed in three steps:
//   1. `CompleteKeysOf` proves each `*_FIELDS` list covers its TS interface (tsc).
//   2. Pydantic emits its own field names to `_fields.json` (pytest).
//   3. This file compares the two.
import { describe, expect, test } from "vitest";
import actionGateFields from "../fixtures/action-gate/_fields.json";
import impactFields from "../fixtures/impact/_fields.json";
import liveEventFields from "../fixtures/live-events/_fields.json";
import toolKnowledgeFields from "../fixtures/tool-knowledge/_fields.json";
import { DIFF_ROW_FIELDS, TOOL_CONFIRMATION_EVENT_FIELDS } from "./action-gate";
import {
  CONSEQUENCE_EVIDENCE_FIELDS,
  CONSEQUENCE_FIELDS,
  IMPACT_NODE_FIELDS,
  IMPACT_RESULT_FIELDS,
  SOL_ACTION_FIELDS,
} from "./impact";
import {
  ACCESS_REVOKED_FIELDS,
  ACCOUNT_STREAM_READY_FIELDS,
  GRAPH_CHANGED_FIELDS,
  GRAPH_CHANGE_COUNTS_FIELDS,
  HARDWARE_DEVICES_CHANGED_FIELDS,
  JOB_UPDATED_FIELDS,
  LAYOUT_CHANGED_FIELDS,
  MEMBERSHIP_CHANGED_FIELDS,
  NOTIFICATION_CREATED_FIELDS,
  PROJECT_STREAM_READY_FIELDS,
  PROJECT_UPDATED_FIELDS,
  SOURCES_CHANGED_FIELDS,
  TEAM_ACTIVITY_FIELDS,
  TEAM_INVITES_CHANGED_FIELDS,
  TEAM_MEMBERS_CHANGED_FIELDS,
  TEAM_PROJECTS_CHANGED_FIELDS,
  TEAM_UPDATED_FIELDS,
} from "./live-events";
import {
  INVOCATION_FIELDS,
  SCREEN_LOCATOR_FIELDS,
  TOOL_KNOWLEDGE_FIELDS,
} from "./tool-knowledge";

const PAIRS: readonly (readonly [string, readonly string[], readonly string[]])[] = [
  ["ToolConfirmationEvent", TOOL_CONFIRMATION_EVENT_FIELDS, actionGateFields.ToolConfirmationEvent],
  ["DiffRow", DIFF_ROW_FIELDS, actionGateFields.DiffRow],
  ["ImpactResult", IMPACT_RESULT_FIELDS, impactFields.ImpactResult],
  ["ImpactNode", IMPACT_NODE_FIELDS, impactFields.ImpactNode],
  ["Consequence", CONSEQUENCE_FIELDS, impactFields.Consequence],
  ["ConsequenceEvidence", CONSEQUENCE_EVIDENCE_FIELDS, impactFields.ConsequenceEvidence],
  ["SolAction", SOL_ACTION_FIELDS, impactFields.SolAction],
  ["ToolKnowledge", TOOL_KNOWLEDGE_FIELDS, toolKnowledgeFields.ToolKnowledge],
  ["Invocation", INVOCATION_FIELDS, toolKnowledgeFields.Invocation],
  ["ScreenLocator", SCREEN_LOCATOR_FIELDS, toolKnowledgeFields.ScreenLocator],
  ["GraphChangeCounts", GRAPH_CHANGE_COUNTS_FIELDS, liveEventFields.GraphChangeCounts],
  ["GraphChanged", GRAPH_CHANGED_FIELDS, liveEventFields.GraphChanged],
  ["HardwareDevicesChanged", HARDWARE_DEVICES_CHANGED_FIELDS, liveEventFields.HardwareDevicesChanged],
  ["LayoutChanged", LAYOUT_CHANGED_FIELDS, liveEventFields.LayoutChanged],
  ["SourcesChanged", SOURCES_CHANGED_FIELDS, liveEventFields.SourcesChanged],
  ["ProjectUpdated", PROJECT_UPDATED_FIELDS, liveEventFields.ProjectUpdated],
  ["JobUpdated", JOB_UPDATED_FIELDS, liveEventFields.JobUpdated],
  ["ProjectStreamReady", PROJECT_STREAM_READY_FIELDS, liveEventFields.ProjectStreamReady],
  ["TeamUpdated", TEAM_UPDATED_FIELDS, liveEventFields.TeamUpdated],
  ["TeamMembersChanged", TEAM_MEMBERS_CHANGED_FIELDS, liveEventFields.TeamMembersChanged],
  ["TeamInvitesChanged", TEAM_INVITES_CHANGED_FIELDS, liveEventFields.TeamInvitesChanged],
  ["TeamProjectsChanged", TEAM_PROJECTS_CHANGED_FIELDS, liveEventFields.TeamProjectsChanged],
  ["TeamActivity", TEAM_ACTIVITY_FIELDS, liveEventFields.TeamActivity],
  ["NotificationCreated", NOTIFICATION_CREATED_FIELDS, liveEventFields.NotificationCreated],
  ["MembershipChanged", MEMBERSHIP_CHANGED_FIELDS, liveEventFields.MembershipChanged],
  ["AccessRevoked", ACCESS_REVOKED_FIELDS, liveEventFields.AccessRevoked],
  ["AccountStreamReady", ACCOUNT_STREAM_READY_FIELDS, liveEventFields.AccountStreamReady],
];

describe("the TypeScript and Pydantic definitions declare the same fields", () => {
  test.each(PAIRS)("%s", (_name, ts, python) => {
    expect([...ts].sort()).toEqual([...python].sort());
  });

  test("every paired contract is covered — a new one must be added here", () => {
    expect(PAIRS).toHaveLength(27);
  });
});
