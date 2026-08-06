// SOLUSDEV-219 (CTR-04) — the impact result contract.
//
// TWO JOBS, same as the gate contract. (1) The fixtures satisfy the TS types —
// the Python twin (packages/api/tests/contracts/test_impact.py) validates the
// SAME files under extra="forbid". (2) The Impact widget is fully buildable
// without the engine: everything a row needs to render, jump to focus, and
// launch a SOL action is asserted here against fixtures alone.
import { describe, expect, test } from "vitest";
import hero from "../fixtures/impact/hero-motor-3a.json";
import noImpact from "../fixtures/impact/no-impact.json";
import truncatedResult from "../fixtures/impact/truncated.json";
import {
  SEVERITIES,
  focusOfImpactNode,
  severityRank,
  toEntityRef,
  worstSeverity,
  type ImpactResult,
} from "./impact";
import type { JsonShapeOf } from "./json";

const RESULTS = [
  hero,
  noImpact,
  truncatedResult,
] satisfies JsonShapeOf<ImpactResult>[];
const HERO = hero as JsonShapeOf<ImpactResult> as ImpactResult;

describe("the severity vocabulary", () => {
  test("matches solus_api.checkers.interface.Severity", () => {
    expect(SEVERITIES).toEqual(["info", "warning", "critical"]);
  });

  test("ranks by real-world impact, not alphabetically", () => {
    expect(severityRank("critical")).toBeGreaterThan(severityRank("warning"));
    expect(severityRank("warning")).toBeGreaterThan(severityRank("info"));
  });

  test("worstSeverity of nothing is the mildest, not a crash", () => {
    // An entity with no consequences is a normal state (a node kept for the
    // traversal path), not an error.
    expect(worstSeverity([])).toBe("info");
    expect(worstSeverity(["info", "critical", "warning"])).toBe("critical");
  });
});

describe("the hero cross-domain case", () => {
  test("one mechanical change reaches at least three domains", () => {
    // The whole product thesis in one fixture: a motor swap that breaks
    // electrical, code and mechanical, none of which the change touched.
    const domains = new Set(HERO.nodes.map((node) => node.domain));
    expect(domains).toEqual(new Set(["electrical", "code", "mechanical"]));
  });

  test("names the driver, the PWM ceiling and the harness", () => {
    expect(HERO.nodes.map((node) => node.label)).toEqual([
      "U3 TB6612FNG",
      "motor_ctl.cpp",
      "drive_harness",
    ]);
  });

  test("the code consequence points at a real location", () => {
    const code = HERO.nodes.find((node) => node.domain === "code")!;
    expect(code.consequences[0]?.evidence[0]?.locator).toBe(
      "firmware/motor_ctl/motor_ctl.cpp:88",
    );
  });

  test("every node's severity is the worst of its own consequences", () => {
    // Precomputed so the widget can sort without walking every consequence.
    for (const node of HERO.nodes) {
      expect(node.severity).toBe(
        worstSeverity(node.consequences.map((c) => c.severity)),
      );
    }
  });
});

describe("every row carries what the widget needs", () => {
  test("a why-this-matters rationale, not just a rule name", () => {
    for (const node of HERO.nodes) {
      for (const consequence of node.consequences) {
        expect(consequence.headline.length).toBeGreaterThan(0);
        // A rationale short enough to be a restatement of the headline is not a
        // rationale; this row is what makes Impact worth reading.
        expect(consequence.rationale.length).toBeGreaterThan(80);
      }
    }
  });

  test("a traversal path back to the focus", () => {
    for (const node of HERO.nodes) {
      expect(node.path.length).toBe(node.distance);
      // The trail starts at the focus — that is what "back to the focus" means.
      expect(node.path[0]?.entity.entity_id).toBe(HERO.focus.entity.entity_id);
    }
  });

  test("enough to jump to focus", () => {
    const driver = HERO.nodes[0]!;
    const focus = focusOfImpactNode(driver);
    expect(focus.entity).toEqual(toEntityRef(driver.entity));
    expect(focus.domain).toBe("electrical");
    expect(focus.label).toBe("U3 TB6612FNG");
    // The breadcrumb the user sees after jumping is the traversal that found it.
    expect(focus.path.map((step) => step.label)).toEqual(["drive_motor"]);
  });

  test("enough to launch a SOL action, or an explicit null", () => {
    const actions = HERO.nodes.flatMap((n) =>
      n.consequences.map((c) => c.action),
    );
    expect(actions.every((a) => a !== null)).toBe(true);
    expect(actions[0]).toMatchObject({ tool: "research.find_compatible_part" });
    // Not every consequence has a fix; the field is nullable rather than absent
    // so a widget never has to distinguish "no action" from "field forgotten".
    const ldo = (truncatedResult as JsonShapeOf<ImpactResult> as ImpactResult)
      .nodes[0]!;
    expect(ldo.consequences[0]?.action).toBeNull();
  });
});

describe("the states a widget must handle", () => {
  test("a change with no consequences is an empty result, not an error", () => {
    expect(noImpact.nodes).toEqual([]);
    expect(noImpact.truncated).toBe(false);
  });

  test("a bounded traversal says so", () => {
    // The engine's traversal is bounded (IMP-01). A widget that did not surface
    // this would present a partial answer as a complete one.
    expect(truncatedResult.truncated).toBe(true);
  });

  test("every fixture carries the change that caused it", () => {
    for (const result of RESULTS)
      expect(result.change.length).toBeGreaterThan(0);
  });

  test("every severity value is one the vocabulary defines", () => {
    // The runtime half of the drift guard — JsonShapeOf defers literal values.
    for (const result of RESULTS) {
      for (const node of result.nodes) {
        expect(SEVERITIES).toContain(node.severity);
        for (const c of node.consequences)
          expect(SEVERITIES).toContain(c.severity);
      }
    }
  });
});
