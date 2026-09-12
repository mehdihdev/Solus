// ADR-034: private machine paths/hints only. Never sync or include in SOL context.
// Python twin: solus_contracts.hardware_local_state; docs/contracts/local-state.md.
export const HARDWARE_LOCAL_STATE_SCHEMA_VERSION = 1;
export const HARDWARE_LOCAL_STATE_FILENAME = "hardware.json";
export const HARDWARE_LOCAL_STATE_MAX_BYTES = 256 * 1024;

export interface HardwareLocalSource {
  readonly path: string;
  readonly contentSha256: string;
}

export interface HardwareLocalBinding {
  readonly lastSeenPath?: string;
}

export interface HardwareLocalAccount {
  readonly sources: Readonly<Record<string, HardwareLocalSource>>;
  readonly bindings: Readonly<Record<string, HardwareLocalBinding>>;
}

export interface HardwareLocalState {
  readonly schema_version: 1;
  readonly accounts: Readonly<Record<string, HardwareLocalAccount>>;
}

type ParseResult =
  | { readonly ok: true; readonly state: HardwareLocalState }
  | { readonly ok: false; readonly reason: "invalid" | "newer" };

const INVALID: ParseResult = { ok: false, reason: "invalid" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function emptyHardwareLocalState(): HardwareLocalState {
  return { schema_version: 1, accounts: Object.create(null) };
}

function record(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === null || prototype === Object.prototype;
}

function fields(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function pathText(value: unknown, max: number): value is string {
  // Count Unicode code points to match Python, and reject unpaired surrogates.
  return (
    typeof value === "string" &&
    value.length > 0 &&
    Array.from(value).length <= max &&
    !Array.from(value).some((char) => {
      const point = char.codePointAt(0)!;
      return (
        point < 0x20 ||
        (point >= 0x7f && point <= 0x9f) ||
        (point >= 0xd800 && point <= 0xdfff)
      );
    })
  );
}

function source(value: unknown): HardwareLocalSource | null {
  if (!record(value) || !fields(value, ["path", "contentSha256"])) return null;
  const { path, contentSha256 } = value;
  if (
    !pathText(path, 4096) ||
    !(
      path.startsWith("/") ||
      /^[A-Za-z]:[\\/]/.test(path) ||
      /^\\\\[^\\]+\\[^\\]+/.test(path)
    ) ||
    typeof contentSha256 !== "string" ||
    contentSha256.length !== 64 ||
    !/^[a-f0-9]{64}$/.test(contentSha256)
  )
    return null;
  return { path, contentSha256 };
}

function binding(value: unknown): HardwareLocalBinding | null {
  if (!record(value) || !fields(value, ["lastSeenPath"])) return null;
  if (!Object.hasOwn(value, "lastSeenPath")) return {};
  return pathText(value.lastSeenPath, 512)
    ? { lastSeenPath: value.lastSeenPath }
    : null;
}

function map<T>(
  value: unknown,
  cap: number,
  parse: (item: unknown) => T | null,
): Record<string, T> | null {
  if (!record(value) || Object.keys(value).length > cap) return null;
  const output: Record<string, T> = Object.create(null);
  for (const [id, raw] of Object.entries(value)) {
    if (id.length !== 36 || !UUID.test(id)) return null;
    const item = parse(raw);
    if (item === null) return null;
    output[id] = item;
  }
  return output;
}

function account(value: unknown): HardwareLocalAccount | null {
  if (!record(value) || !fields(value, ["sources", "bindings"])) return null;
  const sources = map(value.sources, 256, source);
  const bindings = map(value.bindings, 256, binding);
  return sources === null || bindings === null ? null : { sources, bindings };
}

/** Validate parsed JSON. Readers must also bound raw bytes before JSON.parse.
 * Newer or corrupt documents are read-only; a writer must never replace them
 * with an empty fallback. A local hint is not proof of device identity. */
export function parseHardwareLocalState(value: unknown): ParseResult {
  if (!record(value)) return INVALID;
  const version = value.schema_version;
  if (
    typeof version !== "number" ||
    !Number.isSafeInteger(version) ||
    version < 1
  )
    return INVALID;
  if (version > HARDWARE_LOCAL_STATE_SCHEMA_VERSION)
    return { ok: false, reason: "newer" };
  if (!fields(value, ["schema_version", "accounts"])) return INVALID;
  const accounts = map(value.accounts, 16, account);
  if (accounts === null) return INVALID;
  const state: HardwareLocalState = { schema_version: 1, accounts };
  if (
    new TextEncoder().encode(JSON.stringify(state)).byteLength >
    HARDWARE_LOCAL_STATE_MAX_BYTES
  )
    return INVALID;
  return { ok: true, state };
}
