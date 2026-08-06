// SOLUSDEV-220 (CTR-05) — THE COMPILE-TIME PROOF.
//
// This file contains no runtime behaviour. Every `@ts-expect-error` below is an
// ASSERTION that customer-shaped data cannot be constructed as `ToolKnowledge`.
//
// The mechanism, and why it is a test rather than a comment: if any of these
// constructions ever became legal, TypeScript reports
//   error TS2578: Unused '@ts-expect-error' directive
// and `pnpm typecheck` FAILS. Weakening the boundary therefore breaks the build,
// which is what "schema-level, not a convention" means in practice.
//
// To see it work, delete any one directive below and run
// `pnpm --filter @solus/shared-types typecheck` — the line it guards errors.
// Each directive sits directly above the offending PROPERTY, because that is
// where tsc reports both excess-property (TS2353) and type-mismatch (TS2322).
//
// The runtime half is tool-knowledge.test.ts; the Python half is
// packages/api/tests/contracts/test_tool_knowledge.py.

import type { ToolKnowledge } from "./tool-knowledge";
import { controlId, vendorText } from "./tool-knowledge";

/** A legal record, so the failures below are about the illegal part and nothing else. */
const legal: ToolKnowledge = {
  tool: "fusion",
  version_range: ">=2.0 <3.0",
  surface: "toolbar",
  control_id: controlId("fusion.solid.extrude"),
  label: vendorText("Extrude"),
  effect: "create_feature",
  description: vendorText("Adds depth to a closed sketch profile."),
  invocation: {
    menu_path: [vendorText("Create"), vendorText("Extrude")],
    shortcut: "E",
  },
  locator: { x: 0.31, y: 0.06, w: 0.04, h: 0.05 },
  provenance: "vendor_docs",
};

// ── 1. There is no field for anything a customer owns ────────────────────────

const withProject: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's project cannot be referenced
  project_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7",
};

const withEntity: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's graph entity cannot be referenced
  entity_id: "1f0a2b3c-4d5e-4f60-8a91-b2c3d4e5f601",
};

const withDocument: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's CAD document cannot be referenced
  document_id: "d/9a1c2ef4b7d80a3c5e6f1b29",
};

const withTeam: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's team cannot be referenced
  team_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7",
};

const withFile: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's file cannot be referenced
  file_path: "/home/mehdi/robot/chassis.f3d",
};

// ── 2. There is no untyped container to hide content in ──────────────────────

const withProperties: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no free-form property bag
  properties: { width_mm: 62 },
};

const withAttrs: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no attribute map
  attrs: {},
};

const withPayload: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no opaque payload
  payload: "{}",
};

const withMetadata: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no metadata escape hatch
  metadata: {},
};

const withNotes: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no notes field — the classic place a design review gets pasted
  notes: "the customer's gripper is 62mm wide",
};

const withScreenshot: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no screenshot: an image of a customer's screen is customer content
  screenshot_b64: "iVBORw0KGgo=",
};

const withEmbedding: ToolKnowledge = {
  ...legal,
  // @ts-expect-error no embedding: a vector of customer text is still customer text
  embedding: [0.1, 0.2],
};

// ── 3. Prose is branded, so raw strings do not type-check ────────────────────
// This is what stops a customer's part name being assigned to a LEGAL field.

const rawLabel: ToolKnowledge = {
  ...legal,
  // @ts-expect-error `label` is VendorText, not string — it must pass vendorText()
  label: "Chassis Rib Pattern",
};

const rawDescription: ToolKnowledge = {
  ...legal,
  // @ts-expect-error `description` is VendorText, not string
  description: "62mm mount for the drive motor",
};

const rawControlId: ToolKnowledge = {
  ...legal,
  // @ts-expect-error `control_id` is ControlId, not string
  control_id: "d/9a1c2ef4b7d80a3c5e6f1b29",
};

const rawMenuSegment: ToolKnowledge = {
  ...legal,
  invocation: {
    // @ts-expect-error every menu segment is branded — a recent-file entry cannot slip in
    menu_path: ["File", "Open Recent", "~/designs/arm_v3.f3d"],
    shortcut: null,
  },
};

// ── 4. The categorical fields are closed ─────────────────────────────────────

const unknownTool: ToolKnowledge = {
  ...legal,
  // @ts-expect-error a customer's in-house tool is not a modelled tool family
  tool: "customers_internal_cad",
};

const unknownEffect: ToolKnowledge = {
  ...legal,
  // @ts-expect-error the effect vocabulary is closed, not free text
  effect: "does_what_the_customer_asked",
};

const unknownProvenance: ToolKnowledge = {
  ...legal,
  // @ts-expect-error provenance can never be a customer's project
  provenance: "customer_project",
};

// ── 5. The locator is geometry, not pixels of someone's screen ───────────────

const locatorWithImage: ToolKnowledge = {
  ...legal,
  locator: {
    x: 0,
    y: 0,
    w: 1,
    h: 1,
    // @ts-expect-error a locator has no image
    image_b64: "iVBORw0KGgo=",
  },
};

/** Referenced so the assertions above cannot be deleted as unused. */
export const ILLEGAL_CONSTRUCTIONS = [
  withProject,
  withEntity,
  withDocument,
  withTeam,
  withFile,
  withProperties,
  withAttrs,
  withPayload,
  withMetadata,
  withNotes,
  withScreenshot,
  withEmbedding,
  rawLabel,
  rawDescription,
  rawControlId,
  rawMenuSegment,
  unknownTool,
  unknownEffect,
  unknownProvenance,
  locatorWithImage,
] as const;
