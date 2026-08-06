// SOLUSDEV-216 (CTR-01) — the widget manifest schema and the discovery loader.
//
// `collectManifests` takes the RESULT of a glob import, not a glob, so it is
// testable with a plain object — no Vite, no bundler, no canvas. That is the
// same property that lets a lane build a widget before the canvas exists.
import { describe, expect, test } from "vitest";
import { collectManifests, type WidgetManifest } from "./widget";

const Noop = () => null;

function manifest(overrides: Partial<WidgetManifest> = {}): WidgetManifest {
  return {
    id: "parts",
    title: "Parts",
    domains: ["mechanical"],
    size: { preferred: "standard" },
    component: Noop,
    ...overrides,
  };
}

describe("collectManifests", () => {
  test("collects the default export of each module", () => {
    const found = collectManifests({
      "../widgets/parts/widget.manifest.ts": { default: manifest() },
      "../widgets/impact/widget.manifest.ts": {
        default: manifest({ id: "impact", title: "Impact" }),
      },
    });
    expect(found.map((m) => m.id)).toEqual(["impact", "parts"]);
  });

  test("returns manifests in a stable order regardless of glob order", () => {
    // Bundlers do not promise glob ordering; a canvas that rendered widgets in
    // whatever order the loader produced would reshuffle between builds.
    const a = { default: manifest({ id: "alpha" }) };
    const z = { default: manifest({ id: "zulu" }) };
    expect(
      collectManifests({ "/z.ts": z, "/a.ts": a }).map((m) => m.id),
    ).toEqual(["alpha", "zulu"]);
    expect(
      collectManifests({ "/a.ts": a, "/z.ts": z }).map((m) => m.id),
    ).toEqual(["alpha", "zulu"]);
  });

  test("an empty glob yields no widgets rather than throwing", () => {
    // A lane checking out the repo before any widget exists must still boot.
    expect(collectManifests({})).toEqual([]);
  });

  test("accepts an empty domain list as 'relevant everywhere'", () => {
    expect(
      collectManifests({
        "/x/widget.manifest.ts": { default: manifest({ domains: [] }) },
      }),
    ).toHaveLength(1);
  });

  test("accepts the optional lifecycle hooks", () => {
    const found = collectManifests({
      "/x/widget.manifest.ts": {
        default: manifest({
          lifecycle: { mount: () => {}, unmount: () => {} },
        }),
      },
    });
    expect(found[0]?.lifecycle?.mount).toBeTypeOf("function");
  });
});

describe("collectManifests — rejects", () => {
  test("names the offending module when a manifest is malformed", () => {
    expect(() =>
      collectManifests({
        "../widgets/bad/widget.manifest.ts": { default: { id: "bad" } },
      }),
    ).toThrow(/widgets\/bad\/widget\.manifest\.ts/);
  });

  test("rejects a module with no default export", () => {
    expect(() =>
      collectManifests({ "/x/widget.manifest.ts": { manifest: manifest() } }),
    ).toThrow(/default export/);
  });

  test("rejects a duplicate id", () => {
    // Two lanes each shipping a widget called "impact" is exactly the collision
    // manifest self-registration is meant to make impossible to miss.
    expect(() =>
      collectManifests({
        "/a/widget.manifest.ts": { default: manifest() },
        "/b/widget.manifest.ts": { default: manifest() },
      }),
    ).toThrow(/duplicate/i);
  });

  test("rejects an id that is not a stable slug", () => {
    for (const id of ["", "Parts", "parts widget", "parts/impact", "-parts"]) {
      expect(() =>
        collectManifests({
          "/x/widget.manifest.ts": { default: manifest({ id }) },
        }),
      ).toThrow(/id/i);
    }
  });

  test("rejects a non-component", () => {
    expect(() =>
      collectManifests({
        "/x/widget.manifest.ts": {
          default: manifest({ component: "nope" as never }),
        },
      }),
    ).toThrow(/component/i);
  });

  test("rejects an unknown domain", () => {
    expect(() =>
      collectManifests({
        "/x/widget.manifest.ts": {
          default: manifest({ domains: ["thermal" as never] }),
        },
      }),
    ).toThrow(/domain/i);
  });

  test("rejects an unknown size hint", () => {
    expect(() =>
      collectManifests({
        "/x/widget.manifest.ts": {
          default: manifest({ size: { preferred: "huge" as never } }),
        },
      }),
    ).toThrow(/size/i);
  });

  test("rejects a lifecycle hook that is not callable", () => {
    expect(() =>
      collectManifests({
        "/x/widget.manifest.ts": {
          default: manifest({ lifecycle: { mount: 1 as never } }),
        },
      }),
    ).toThrow(/lifecycle/i);
  });
});
