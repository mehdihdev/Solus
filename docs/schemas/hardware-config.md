# Hardware configuration storage and migration

**Last updated:** 2026-11-15 (SOLUSDEV-326: a stored config lists its brains). **Status:**
approved design for SOLUSDEV-251; implementation and migration results must be recorded
separately in the completion report.
**Authority:** ADR-034 amendment 2026-09-07; [hardware routes](../api/hardware.md),
[hardware architecture](../architecture/hardware-onboarding.md),
[private local-state contract](../contracts/local-state.md).

## Storage ownership

Configuration remains in project `.solus` `solus_entries`, kind `config`, section `hardware`,
with a `hardware_config` graph node under its existing section and one manual `configures`
edge to its subject. A subject is a project-owned robot or eligible real part; a robot owner
is optional for a part. Provider-sourced entities are configured through manual CONFIG entries
and relations without changing provider attributes, external_ref or source containment.

Extend `SolusEntry` with nullable `configured_entity_id` (graph entity FK) and `config_version`
(nonnegative integer; a live configured entry starts at 1). Both are meaningful only for CONFIG;
non-CONFIG entries have no configured subject and version 0. Enforce a CONFIG-only check and,
after data preflight/backfill, a partial unique index on `(project_id, configured_entity_id)`
for live CONFIG rows. A configured subject, entry, section and configures target must all
belong to the same project; service validation enforces this alongside the relational FKs.
Soft-deleted historical entries do not block a new explicit configuration.

`configured_entity_id` and the validated `configures` relation agree. A manual subject may carry
`hardware_config_ref` as a convenience reference, never the sole lookup key. Imported subjects
must not receive this attribute. A part's existing entity version is the ownership precondition;
assignment increments it under the same transaction as the manual edge change. CONFIG version
is independent and increments on configuration writes. Reads never initialize config entries.

## HardwareConfig v2

The API-local Pydantic schema is implemented in `packages/api/src/solus_api/hardware/config.py`.
The stored v2 type is `EntityHardwareConfig`; `ConfigDraft` omits entity_id for creation.
`HardwareConfig` v1 remains the explicit runtime/plugin compatibility type. No protected
connector, focus, driver or telemetry interface changes.

| Field              | Shape / bound                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `schema_version`   | Required literal integer 2.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `entity_id`        | Required real subject UUID; agrees with route and configured_entity_id.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `component`        | Optional/null; existing PartConfig fields for this subject: calibration, limits, telemetry, firmware, lifecycle.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `identity`         | List (at most 16, default empty) of brains `{kind,binding?,via?,protocol?}` (SOLUSDEV-326). `kind` host\|mcu\|onboard (default host). `binding` portable `{kind,binding,vid?,pid?}`; kinds usb_serial, usb_can, ble, bt_classic, wifi, ethernet, ros2; binding 1–128 non-whitespace characters without slash; VID/PID 0–65535; no local last_seen_path; absent until a device is bound. Bound brains have unique device refs. `via` names another brain's device ref in this config; no brain is reached through itself. `protocol` is that brain's driver slug (1–64 characters) and at most 32 scalar parameters, validated against the installed driver schema before connection. |
| `bus_map`          | At most 256 `{protocol,address,part_entity_id?,model?,brain?}` entries; protocol/address 1–64 characters, address without whitespace, model at most 128. Targets must be eligible live parts in this project. `brain` is the device ref of the brain the row sits behind; null means the config's only brain and is refused when there are several. Uniqueness is per (brain, protocol, address): the same address on two brains is two endpoints.                                                                                                                                                                                                                                   |
| `disambiguated_by` | Optional literal user; records reviewed choice, never permanent ambiguous-port consent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `provenance`       | Dotted field path → `{by,source?}`; existing library/repo/user/sol/detected values. Prefixes cover descendants, longest prefix wins. Source is a portable label/opaque reference, at most 512 characters.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

Component bounds preserve the existing model: calibration mode is optional
`degrees|range_0_100|range_m100_100|linear|raw`, calibration and limit values each have at most
64 numeric entries; telemetry has at most 64 `{name,unit?,range?,display?}` channels (name 1–128,
unit ≤32; see Channels below);
firmware uses the existing scalar dictionary; lifecycle is
`planned|ordered|received|installed|live`. Calibration retains `owner:repo|solus` and portable
optional source. Numbers must be finite. Unknown fields are rejected throughout. The full
encoded UTF-8 document is at most 64 KiB, including provenance. Every valued leaf outside
schema_version/entity_id/provenance has provenance; null/empty containers require none. An
omitted/null component saves without lifecycle provenance; a present component defaults to
planned and requires provenance for that valued lifecycle field.

A component cannot contain another part-config map. Connection-owner bus entries reference
part UUIDs; runtime assembly resolves those parts' current component entries into the existing
driver aggregate without persisting another copy. Missing calibration/capabilities are valid
for storage and explicit setup requirements for operations that need them. Detected observations
cannot overwrite conflicting saved decisions without review. Stale connection-owner bindings
after reassignment are nonoperational pending explicit resolution; their evidence is retained.

Portable source references contain no raw absolute POSIX/Windows path, credential or tty hint.
Verified calibration values remain shared. The opaque reference resolves to the current
account's private picker-authorized source only on the local machine; changed digest requires
review. Shared history, events and model context must not expose old or new private paths.

### Brains (SOLUSDEV-326)

The pre-326 shape (one `identity`, a top-level `protocol`) is still read: a before-validator on
`ConfigDraft` (so on every validated read, `config_of`, the per-entity routes and the creation
body) upgrades it to `identity: [{kind: host, binding, via: null, protocol}]`, or `[]` when it
named neither. A body whose `provenance` is not an object of paths is left as sent, so field
validation refuses it (422). An identity-less driver (a library platform) stays as one unbound brain rather
than being dropped. Records move with the leaves: `identity` → `identity.0`,
`identity.<f>` → `identity.0.binding.<f>`, `protocol[.<f>]` → `identity.0.protocol[.<f>]`, and
the new `identity.0.kind` leaf takes the record that covered the old identity (else the
driver's), so every longest-prefix lookup finds the record it found before; stale records of an
absent identity are dropped. `.solus` reads (`serialize_entry`) return the upgraded document.
`schema_version` stays 2 and stored rows are not rewritten; the next write stores the list.

The driver input stays the v1 `HardwareConfig` with exactly one identity. `resolve_runtime_config`
returns the v1 aggregate its readers know (identity/protocol of the FIRST brain, every active
bus row with its `brain`, every part) and `per_brain()`: one v1 document per brain, its rows
only (no `brain` key) and, when there are several brains, only the parts those rows map. A
one-brain robot's single document equals its aggregate byte for byte, so digests and driver
documents are unchanged. Sessions open the first brain; brains 2..N get no port hint.

The v1 adapter (`put_config`) treats a v1 document as speaking for ONE brain and merges it into
the stored list by device ref: the brain with that device is updated, else the first unbound
brain is bound, else the device joins as a new brain; a document without an identity speaks for
the first brain. It never drops another brain, and rows the document leaves implicit name its
brain once there are several. A change v1 cannot express (orphaning a brain's rows) is 409
`config_upgrade_required`; removing or reordering brains is a per-entity PUT. An unchanged round
trip (same values and the same record on every leaf, however keyed) writes no version. A config
names only parts everyone who can see it can see (api/hardware.md §1a).
`hand_over_brain` moves one brain and its rows from one subject's config to another in the
caller's transaction (a lone part's board joining a robot) while one config per device holds.
A result the target cannot hold (a 17th brain, a `via` naming a brain that stays behind) is 422
`validation_error` with the reason. A target whose only brain is unbound and owns implicit rows
is 409 `config_conflict`.

Revision a26000000002 reads payloads with a frozen copy of the pre-326 v2 schema and splitter
(`migrations/hardware_config_v2.py`), never the live model.

### Channels (SOLUSDEV-326)

A telemetry channel may say how the Live Bench draws it. Both fields are optional and additive:

- `range` `{min, max}`: a DISPLAY range in the channel's unit. Both numbers are finite and
  `min < max`; anything else is refused (422 on the routes). The chart spans at least this range,
  and a reading outside it widens the chart, never hides it. It is never a motion bound:
  envelopes, limits and calibration keep their own precedence.
- `display`: `plot|angle|orientation|video|scan|points|state|text`, default `plot`. It is never
  null; `null` is refused like any unknown value.

An absent range and a `plot` display, whether defaulted or written out, are left out of every
dump. A plain channel therefore reads, digests, and asks for provenance exactly as before. A set
range or a non-`plot` display is a valued leaf and needs its record, as any other leaf does
(`component.telemetry.<i>.display`, `component.telemetry.<i>.range.min|max`, or a covering
prefix). The v1 driver document carries a part's channels whole. The robot connection
publishes each channel's non-default display and range as the `channel_display` device fact,
keyed like the driver's channel roles, and the bench series carries them
(`docs/contracts/telemetry-packet.md` §2a).

### Derived binding relations

A manual `binds` relation runs from the CONFIG graph node to each endpoint part with attributes
`{device_ref,address,protocol,config_version,enabled,disabled_reason?}`: one bare endpoint per
bound brain and one per mapped row, on the brain the row sits behind. It is a derived,
validated connection index; `configures` remains subject authority. Validate project scope,
current CONFIG version, source config ownership and eligible target before using an enabled
binding. Runtime assembly and the resolver use only current enabled unambiguous bindings.
Assignment disables bindings from a previous owner with `disabled_reason:ownership_changed`
without erasing saved bus-map evidence or part calibration. Explicit reviewed versioned CONFIG
PUT rebuilds/re-enables appropriate bindings. Configuration/assignment/deletion transactions
publish cache invalidation only after commit; rollback cannot expose a half-updated mapping.

## Reviewed operation records

Use a dedicated `hardware_operations` table, not billing idempotency storage:

| Column                  | Purpose                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| id                      | Operation UUID primary key.                                                                 |
| project_id / user_id    | Authorized scope; project/user FKs.                                                         |
| idempotency_key         | Client UUID, unique together with project_id and user_id.                                   |
| operation               | Bounded operation kind, maximum 64 characters.                                              |
| payload_digest          | 64 lowercase hex SHA-256 over canonical validated operation/target/payload/review revision. |
| response                | Bounded JSONB saved result, at most 64 KiB; IDs and safe response data only.                |
| created_at / expires_at | UTC timestamps, expires 24 hours after creation.                                            |

Index expiry for bounded cleanup. Creation reserves/checks the unique tuple within the same
transaction as graph/config mutations; a concurrent duplicate waits/replays, never double
creates. Same tuple/digest returns the recorded saved result; different digest is 409. Expired
records can be removed and keys reused after 24 hours; a client reconnects with saved IDs instead
of depending on indefinite replay. A transaction failure rolls back its record. Connection
starts only after commit and its transient outcome never turns saved hardware into a failed
creation. Store no private paths/secrets and emit no duplicate creation event on replay.

## Migration and rollback

Schema and data migration are separate, immutable Alembic revisions with a single head.
Introduce nullable fields/table first. Before enforcing uniqueness or changing live documents,
preflight live and historical CONFIG entries, including deleted robots. Report duplicate
subjects, differing embedded part copies, ambiguous ownership, invalid/cross-project references,
endpoint collisions and invalid provenance. Fail closed on unresolved conflicting operational
values; do not select a calibration winner, drop parts or install a partial migration.

Migrate valid robot CONFIG entries in place, preserving entry and graph-node UUIDs, existing
names, timestamps/history and configures targets. Extract each embedded part component into its
own CONFIG entry with a new entry/node UUID only because no such entry existed before; keep the
part UUID. Rewrite provenance from `parts.<part_id>.*` to `component.*` without losing its source
or author. Transfer robot-level firmware into that subject's component. Each physical connection
owner retains its identity/protocol/bus map; no transport is assigned by drawing containment.

Retain detached/deleted-robot parts and their configuration. Preserve deleted ownership history,
canonical links, provider source/external_ref, provider containment and saved coordinates.
Conflicting historical values may be retained as bounded migration evidence associated with the
subject, but are never enabled as calibration/limits until a user explicitly resolves them.
Document exact evidence storage in the implemented migration before applying it to live data;
preflight conflicts do not authorize inventing new active values.

Replace private paths in active shared config/provenance with opaque source references and safe
labels/digests. Do not infer that a legacy path belongs to this host, read it during migration,
or copy it into new shared history. Preserve validated calibration values and mark unresolved
sources as requiring relinking on the user's actual machine. Existing evidence that is invalid
for operational use must remain nonoperational.

Validate all transformed documents/references, backfill version 1 and subject IDs, then enforce
the unique live-subject index/check. Repeatable application does not create another part entry
or alter graph IDs. Test both transactional first-write races and migrations against PostgreSQL.
Downgrade fails clearly if v2 standalone/independent part state cannot be represented in v1;
it must not drop those values to produce a superficially successful rollback. Do not mutate the
user's live project until the fixture/copied-data migration has passed validation.

## Required evidence

Migration tests cover duplicate/conflicting data, private-path removal, detached retention,
unchanged existing IDs, provenance, rollback failure and repeatability. Route tests cover
read-only absence, config/ownership version conflicts, duplicate first writes, replay isolation,
wrong-project subjects/parents/parts, viewer rejection and save-before-connect failure.
Resolver tests prove imported external_ref preservation, binding ambiguity refusal and cache
invalidation. Results belong in the SOLUSDEV-251 completion and Cowork QA documents.

### SOLUSDEV-260 explicit legacy relinking

Approved in-session: legacy sources have no file-content digest, and migration
must not open their private paths. Mint one opaque `source:<UUIDv5>` per project
and exact legacy source string, using the project UUID as namespace. All parts
citing that string share the reference. Do not canonicalize a path on a different
machine. The authenticated local picker explicitly binds the migrated reference
to a selected file and records its actual content digest only in private state.
The token supplies no file access authority and is not a content-integrity claim.
Known digest changes retain the existing explicit review requirement. This changes
no local-state document fields or protected interface.

An explicit relink preserves its requested historical reference even if another local
reference already names the selected canonical file. Such compatibility aliases retain
existing shared references; they do not silently rewrite configs. Different legacy path
spellings can require this. New picker selections reuse an existing same-file reference,
and relinking to changed known bytes still requires review.
