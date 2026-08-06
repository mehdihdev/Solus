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
];

describe("the TypeScript and Pydantic definitions declare the same fields", () => {
  test.each(PAIRS)("%s", (_name, ts, python) => {
    expect([...ts].sort()).toEqual([...python].sort());
  });

  test("every paired contract is covered — a new one must be added here", () => {
    expect(PAIRS).toHaveLength(10);
  });
});
