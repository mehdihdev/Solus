// SOLUSDEV-217 (CTR-02) — the focus contract, asserted executably.
//
// The reference store is what WS-03 and every widget lane develop against until
// WS-01 lands, so its behaviour IS the contract, not a convenience.
import { describe, expect, test, vi } from "vitest";
import { createFocusStore, descend, isSameEntity, type Focus } from "./focus";

const motor: Focus = {
  entity: {
    projectId: "11111111-1111-1111-1111-111111111111",
    entityId: "aaaa1111-0000-0000-0000-000000000001",
  },
  domain: "mechanical",
  label: "drive_motor",
  path: [],
};

const driver: Focus = {
  entity: {
    projectId: motor.entity.projectId,
    entityId: "aaaa1111-0000-0000-0000-000000000002",
  },
  domain: "electrical",
  label: "TB6612FNG",
  path: [],
};

describe("createFocusStore", () => {
  test("starts empty", () => {
    expect(createFocusStore().get()).toBeNull();
  });

  test("starts at an initial focus when given one", () => {
    expect(createFocusStore(motor).get()).toEqual(motor);
  });

  test("set replaces the focus and get returns it", () => {
    const store = createFocusStore();
    store.set(motor);
    expect(store.get()).toEqual(motor);
    store.set(driver);
    expect(store.get()).toEqual(driver);
  });

  test("set(null) clears the focus", () => {
    const store = createFocusStore(motor);
    store.set(null);
    expect(store.get()).toBeNull();
  });
});

describe("createFocusStore — notification", () => {
  test("notifies every subscriber on change", () => {
    const store = createFocusStore();
    const a = vi.fn();
    const b = vi.fn();
    store.subscribe(a);
    store.subscribe(b);
    store.set(motor);
    expect(a).toHaveBeenCalledWith(motor);
    expect(b).toHaveBeenCalledWith(motor);
  });

  test("does not notify on a no-op set", () => {
    // A widget re-emitting the focus it was just handed must not loop the app.
    const store = createFocusStore(motor);
    const listener = vi.fn();
    store.subscribe(listener);
    store.set(motor);
    expect(listener).not.toHaveBeenCalled();
  });

  test("notifies when the same entity is reached by a different route", () => {
    // Same entity, same trail length, different edge — a different focus. A
    // breadcrumb that did not update here would misreport how the user got there.
    const store = createFocusStore(
      descend(motor, { ...driver, relation: "drives" }),
    );
    const listener = vi.fn();
    store.subscribe(listener);
    store.set(descend(motor, { ...driver, relation: "connected_to" }));
    expect(listener).toHaveBeenCalledTimes(1);
  });

  test("unsubscribe stops delivery", () => {
    const store = createFocusStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    unsubscribe();
    store.set(motor);
    expect(listener).not.toHaveBeenCalled();
  });

  test("unsubscribing twice is harmless", () => {
    const store = createFocusStore();
    const unsubscribe = store.subscribe(vi.fn());
    unsubscribe();
    expect(() => unsubscribe()).not.toThrow();
  });

  test("a listener unsubscribing during a notify does not skip its neighbour", () => {
    // Iterating the live set while a listener removes itself is the classic way
    // to silently drop the next subscriber.
    const store = createFocusStore();
    const second = vi.fn();
    const unsubscribeFirst = store.subscribe(() => unsubscribeFirst());
    store.subscribe(second);
    store.set(motor);
    expect(second).toHaveBeenCalledTimes(1);
  });

  test("a throwing listener does not stop the others or corrupt the state", () => {
    const store = createFocusStore();
    const healthy = vi.fn();
    store.subscribe(() => {
      throw new Error("widget blew up");
    });
    store.subscribe(healthy);
    expect(() => store.set(motor)).not.toThrow();
    expect(healthy).toHaveBeenCalledWith(motor);
    expect(store.get()).toEqual(motor);
  });
});

describe("descend", () => {
  test("appends the current focus to the trail and records the relation", () => {
    const next = descend(motor, {
      entity: driver.entity,
      domain: "electrical",
      label: "TB6612FNG",
      relation: "drives",
    });
    expect(next.entity).toEqual(driver.entity);
    expect(next.domain).toBe("electrical");
    expect(next.path).toEqual([
      {
        entity: motor.entity,
        domain: "mechanical",
        label: "drive_motor",
        relation: "drives",
      },
    ]);
  });

  test("keeps the existing trail in order", () => {
    const first = descend(motor, {
      entity: driver.entity,
      domain: "electrical",
      relation: "drives",
    });
    const second = descend(first, {
      entity: {
        projectId: motor.entity.projectId,
        entityId: "aaaa1111-0000-0000-0000-000000000003",
      },
      domain: "code",
      relation: "controlled_by",
    });
    expect(second.path.map((step) => step.domain)).toEqual([
      "mechanical",
      "electrical",
    ]);
    expect(second.path.map((step) => step.relation)).toEqual([
      "drives",
      "controlled_by",
    ]);
  });

  test("does not mutate the focus it was given", () => {
    const before = structuredClone(motor);
    descend(motor, {
      entity: driver.entity,
      domain: "electrical",
      relation: "drives",
    });
    expect(motor).toEqual(before);
  });

  test("refuses to cross a project boundary", () => {
    // A focus is scoped to one project; a trail that spans two would carry
    // another team's entity into a widget's render path.
    expect(() =>
      descend(motor, {
        entity: {
          projectId: "22222222-2222-2222-2222-222222222222",
          entityId: driver.entity.entityId,
        },
        domain: "electrical",
        relation: "drives",
      }),
    ).toThrow(/project/i);
  });
});

describe("isSameEntity", () => {
  test("compares project and entity, not label or domain", () => {
    expect(isSameEntity(motor.entity, { ...motor.entity })).toBe(true);
    expect(isSameEntity(motor.entity, driver.entity)).toBe(false);
    expect(
      isSameEntity(motor.entity, {
        projectId: "22222222-2222-2222-2222-222222222222",
        entityId: motor.entity.entityId,
      }),
    ).toBe(false);
  });
});
