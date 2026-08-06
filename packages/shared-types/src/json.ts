// LANE 0 — fixture typing support.
//
// The contracts are validated from BOTH sides against one set of JSON fixtures:
// Pydantic `model_validate` under extra="forbid", and `tsc` here. That is what
// stops the TS and Python definitions of one shape drifting apart, given that
// these types have no route and so cannot go through the OpenAPI pipeline.
//
// One wrinkle makes a naive `satisfies` fail: TypeScript widens string literals
// in `.json` imports, so a field typed as a literal union (`"approve" | "reject"`)
// arrives as `string` and the assertion fails for a reason that has nothing to do
// with drift.

/**
 * `T` as a `.json` import sees it: identical structure, string-literal unions
 * widened to `string`.
 *
 * Every FIELD check survives — a renamed, missing, or extra field still fails
 * `tsc`, which is the drift we are guarding. Only the literal VALUES are
 * deferred, and those are asserted at runtime against the exported const arrays
 * (`CONFIRMATION_STATUSES`, `SEVERITIES`, ...) that define them.
 */
/**
 * Compile-time proof that `F` lists EVERY key of `T`.
 *
 * Resolves to `F` when the list is complete and to a never-assignable error
 * tuple when it is not, so an unlisted field fails `tsc` and NAMES ITSELF in the
 * message. Use it to declare the runtime field list a contract exports:
 *
 * ```ts
 * const FIELDS = ["a", "b"] as const;
 * export const FOO_FIELDS: CompleteKeysOf<Foo, typeof FIELDS> = FIELDS;
 * ```
 *
 * WHY THIS EXISTS. `satisfies` performs excess-property checking only on FRESH
 * OBJECT LITERALS. A fixture imported from `.json` is a variable, so ordinary
 * width subtyping applies and a value carrying EXTRA keys still satisfies the
 * type. Verified: adding an undeclared field to a fixture left `tsc` silent,
 * while renaming a required one errored. So `satisfies JsonShapeOf<T>` alone
 * catches renamed and missing fields but NOT added ones — and "add a field" is
 * the change six lanes will make most often (docs/WORKTREES.md §5 calls additive
 * changes cheap).
 *
 * Pairing this with the generated `_fields.json` manifest closes it: Pydantic's
 * field names are emitted from the Python suite, the TS list is proven complete
 * against the TS interface here, and the two lists are compared at runtime. A
 * field added on either side now breaks one of the two suites, which is what the
 * drift guard claimed all along.
 */
export type CompleteKeysOf<T, F extends readonly (keyof T)[]> =
  Exclude<keyof T, F[number]> extends never
    ? F
    : ["field list is missing:", Exclude<keyof T, F[number]>];

export type JsonShapeOf<T> = T extends string
  ? string
  : T extends number | boolean | null | undefined
    ? T
    : T extends readonly (infer E)[]
      ? JsonShapeOf<E>[]
      : T extends object
        ? { -readonly [K in keyof T]: JsonShapeOf<T[K]> }
        : T;
