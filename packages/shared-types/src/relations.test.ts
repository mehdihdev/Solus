// SOLUSDEV-320 — the relation vocabulary is pinned to the Python-generated manifest.
import { describe, expect, test } from "vitest";
import manifest from "../fixtures/relations/_values.json";
import {
  CANDIDATE_THRESHOLD,
  EDGE_EVIDENCE_FIELDS,
  EDGE_ORIGINS,
  EVIDENCE_KINDS,
  MATRIX_CELLS,
  RELATION_CLASS,
  RELATION_CLASSES,
  RELATION_TYPES,
  isCandidate,
  matrixCell,
  normalizeDomainPair,
  relationClass,
} from "./relations";

describe("the vocabulary matches solus_contracts.relations", () => {
  test("classes, types, origins, cells and evidence kinds", () => {
    expect([...RELATION_CLASSES]).toEqual(manifest.RelationClass);
    expect([...RELATION_TYPES]).toEqual(manifest.RelationType);
    expect(RELATION_CLASS).toEqual(manifest.RELATION_CLASS);
    expect([...EDGE_ORIGINS]).toEqual(manifest.EdgeOrigin);
    expect([...MATRIX_CELLS]).toEqual(manifest.MatrixCell);
    expect([...EVIDENCE_KINDS]).toEqual(manifest.EvidenceKind);
    expect([...EDGE_EVIDENCE_FIELDS].sort()).toEqual(manifest.EdgeEvidence);
    expect(CANDIDATE_THRESHOLD).toBe(manifest.CANDIDATE_THRESHOLD);
  });
});

describe("helpers", () => {
  test("relationClass reads the table and never throws", () => {
    expect(relationClass("powers")).toBe("dependency");
    expect(relationClass("same_as")).toBe("identity");
    expect(relationClass("teleports")).toBe("legacy");
  });
  test("normalizeDomainPair is alphabetical and strict", () => {
    expect(normalizeDomainPair("electrical", "code")).toBe("code<->electrical");
    expect(normalizeDomainPair("code", "electrical")).toBe("code<->electrical");
    expect(normalizeDomainPair("software", "code")).toBeNull();
  });
  test("matrixCell keeps direction and maps code to software", () => {
    expect(matrixCell("code", "electrical")).toBe("software->electrical");
    expect(matrixCell("electrical", "code")).toBe("electrical->software");
    expect(matrixCell("project", "code")).toBeNull();
  });
  test("isCandidate is inferred below the threshold only", () => {
    expect(isCandidate("inferred", 0.55)).toBe(true);
    expect(isCandidate("inferred", 0.8)).toBe(false);
    expect(isCandidate("manual", 0.1)).toBe(false);
    expect(isCandidate(undefined, undefined)).toBe(false);
  });
});
