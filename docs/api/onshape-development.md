# Onshape development operations — SOLUSDEV-261

Extends the existing W0-04 operation registry and action gate, not a new HTTP API.
Uses the existing graph-backed project Source, customer OAuth, transport-free
operations and confirmation previews. All IDs validated; all calls quota-metered.
Live part/geometry/feature identity must be read before proposing changes. Source
and destination documents for insertion must both be tracked in the project.

First additions (schema frozen):

- `onshape.list_parts`: document_id + element_id required, workspace_id optional.
  GET `/api/v6/parts/d/{d}/w/{w}/e/{e}`; returns `{parts: [...]}` with actual names/IDs.
- `onshape.get_part_bounds`: above plus required part_id.
  GET `/api/v6/parts/d/{d}/w/{w}/e/{e}/partid/{part}/boundingboxes`; returns vendor bounds.
  Requires finite numeric low/high coordinates on all three axes, with low ≤ high;
  malformed or error-shaped vendor responses are rejected.
- `onshape.insert_part`: target document_id/element_id/workspace_id plus required
  source_document_id/source_element_id/part_id/source_microversion_id. Inserts one
  part pinned to an observed immutable microversion through
  POST `/api/v6/assemblies/d/{d}/w/{w}/e/{e}/instances` with published
  BTAssemblyInstanceDefinitionParams fields. No caller-supplied raw URLs or arbitrary
  payload. Requires confirmation; preview reads target assembly and donor part,
  displays both document/element/part identities and target current microversion
  fingerprint. Changes between preview and approval fail the existing stale gate.
  Returns real instance IDs; no successful mutation is inferred from HTTP status
  when the vendor response reports failure. Donor must be independently authorized.

Existing update_feature, set_variable, resolve_reference, get_body_details,
get_mass_properties and get_assembly_definition are reused. Sketch/cut and mate
parameter schemas will be appended after live featurespec evidence; they must not
be guessed or implemented as an arbitrary vendor-write escape hatch.

`get_feature_tree` must expose each feature's live `parameters` alongside name,
feature_id and feature_type, preserving actual parameter IDs and expression/value
fields. These are untrusted vendor data, not executable instructions. The existing
update_feature validator and fresh preview gate remain authoritative for writes.
Feature specs must read the vendor's live parameter-spec collection rather than
claiming an empty parameter list when the schema contains parameters.

Feature lookup used by update/preview accepts current flat feature objects and
legacy message envelopes. A `BTMParameterQuantity-147` edits its authoritative
`expression`; computed value/units/integer metadata is preserved rather than
misclassified as a second writable field. Unknown ambiguous parameter shapes
continue to fail closed.
Requested and live feature IDs must satisfy the existing path-safe ID grammar.
The complete live parameter collection must be valid with unique, nonempty IDs;
preview/update must never silently discard malformed entries before rewriting a
feature.

To keep a complete parameter record within the model tool-result limit,
`get_feature_tree` accepts optional `feature_id` and `get_feature_specs` accepts
optional `feature_type`. These filter the validated vendor collection to the exact
requested feature/type before returning it. A missing match fails explicitly;
omitting the filter preserves the existing list behavior. Descriptions direct
models to use these filters before editing rather than reasoning from truncated
feature collections.

After a successful native write approval, the existing confirmation result adds
`value.graph_sync`: `{status: "queued", job_id}` or `{status: "failed" |
"unavailable", message}`. The CAD result remains successful when scheduling
fails. The persisted tool turn distinguishes applied CAD from pending or failed
graph synchronization. The existing source sync endpoint is the recovery action.
This changes no route, request schema, or approval requirement. Only the current
project's connected, nonrevision source tracking the written document is eligible;
the bound account must still be connected and match the source's grant reference.

## Complete geometry pages

Live verification found that the raw body-details response exceeds the model's
result limit before edge definitions arrive. `get_body_details` gains optional
`body_id`, `collection` (`faces`, `edges`, `vertices`), `offset` (integer >=0),
`limit` (integer 1..10, default 1), and `expected_fingerprint` (four 16-hex SHA-256
chunks separated by colons). Paging requires both body_id and collection; other
page fields without these are invalid. Omission preserves the legacy response.
No vendor endpoint or authorization boundary changes: fetch the existing body
details, select the exact observed body, then page its requested collection.

Paged results are `{body_id,collection,total,offset,next_offset,fingerprint,items}`.
The fingerprint covers the entire selected body, not just the returned page.
Subsequent pages must echo it; a changed body refuses with stale_state. Once total
and fingerprint are known, independent offsets may be requested in parallel,
with each checking the fingerprint. This avoids spending a model round per page.
**ADR-038 (SOLUSDEV-312):** pages are sliced from ONE payload fetched per
immutable microversion and cached, so extra pages cost no provider calls.
A missing
body or absent collection is not_found; malformed/duplicate vendor identities
are api_error, never an invented empty collection. An observed empty list is valid.
Return only whole items. Keep a conservative serialized page bound below 3000
characters, including ASCII escaping, `<` escaping and twelve characters per
dictionary entry reserved for possible redaction expansion. Tests pass accepted
pages through the actual model containment layer to prove they remain parseable.
Reduce
the requested page length when necessary; next_offset reflects the actual number
returned. A single oversized item refuses with result_too_large rather than
providing a truncated geometry reference. Models must not treat page fingerprints
as vendor microversions or authority to write; the existing live write preview
remains required.

## Scoped blind extrusion cut

`onshape.extrude_cut` adds one built-in `extrude` feature to a Part Studio.
Required arguments: document_id, element_id, sketch_feature_id, part_id,
name (1..120 characters), depth_mm (finite number >0 and <=10000),
opposite_direction (boolean). workspace_id remains optional. Unknown fields are
rejected. All sketch regions from the named existing `newSketch` are selected;
the preview explicitly says so. This first operation has one explicit target
part, no automatic merge scope, arbitrary query, script, or caller vendor payload.

The operation uses GET and POST `/api/v6/partstudios/d/{d}/w/{w}/e/{e}/features`,
GET its `/featurespecs`, and the existing parts listing. Preview verifies the
actual unsuppressed sketch and target part, validates the required live built-in
parameter specifications, and includes the feature-tree microversion, complete
input identity, depth in mm, direction, and scope. Missing or ambiguous live
identity/specification fails closed. Approval uses the existing fresh-preview
comparison and the POST carries sourceMicroversion plus rejectMicroversionSkew.

Published BTMFeature-134 payload: featureType=extrude; bodyType enum
ExtendedToolBodyType=SOLID; operationType enum NewBodyOperationType=REMOVE;
entities is BTMParameterQueryList-148 containing a
BTMIndividualSketchRegionQuery-140 with the observed sketch featureId;
endBound enum BoundingType=BLIND; depth BTMParameterQuantity-147 expression in mm;
oppositeDirection BTMParameterBoolean-144; defaultScope=false; booleanScope is
BTMParameterQueryList-148 with BTMIndividualQuery-138 deterministicIds=[part_id].
These parameter IDs/types and enum names were verified against the live v6
built-in extrude specification on 2026-09-12. The public feature-access guide
provides the sketch-region query shape. Vendor defaults are not caller input.

Success requires a returned new feature ID and a subsequent feature-tree read
showing that exact extrude with no regeneration error and the intended parameters.
An uncertain POST or failed post-write verification returns mutation_unverified
with instructions to inspect before retrying, never a retryable credential error
that could repeat the mutation. Graph synchronization uses the existing successful
native-write hook. The tool retains requires_confirmation and write tags.

## Circle sketch on an observed planar face

`onshape.create_circle_sketch` adds one `newSketch` to the chosen Part Studio.
Required: document_id, element_id, body_id, face_id, name (1..120 characters),
center_x_mm and center_y_mm (finite numbers, absolute value <=10000), radius_mm
(finite >0 and <=10000). workspace_id is optional. Coordinates refer to Onshape's
local sketch plane, explicitly stated in the preview; they are not world axes.

Preview reads the feature tree and body details, requires exactly one observed
body/face with planar surface and finite origin/normal, and verifies the live
newSketch specification's sketchPlane query type. It includes document/element,
body/face, plane origin/normal, the geometry fingerprint and source microversion,
name and centre/radius in mm. It must not infer a deterministic face ID from a
name or accept arbitrary query strings. The write repeats the same validation and
uses sourceMicroversion/rejectMicroversionSkew in the feature POST.

Published payload: BTMSketch-151, featureType=newSketch; sketchPlane query list
with BTMIndividualQuery-138 deterministicIds=[face_id]; one BTMSketchCurve-4 entity
with BTCurveGeometryCircle-115 geometry, xDir=1, yDir=0, clockwise=false,
centerId/entityId authored by Solus, and no caller-supplied constraints. Convert
all numeric mm inputs to metres by dividing by1000. Live existing sketch geometry
on 2026-09-12 has X extrema +/-0.073025 while the measured part width is146.05mm,
confirming the serialization unit independently of the public guide's ambiguous
circle-example prose. Do not infer world-space placement from local coordinates.

Readback must find the returned new sketch ID exactly once, verify its healthy
feature state, selected plane and complete circle geometry (including tolerance
for finite numeric serialization), and return the actual sketch ID and geometry.
Failed/uncertain post-write verification is mutation_unverified and cannot replay
the POST through credential refresh. Existing confirmation, authorization, quota
and graph-sync behavior are unchanged.

### Authoring approval and live serialization details

The new sketch/cut tools require complete previews: failed reads cannot park
argument-only cards. A task-local, single-use preview ticket binds canonical public
arguments and exact observed operation rows to execution. Execution compares its
fresh observation before POST; a changed model, workspace, or specification is
stale. No caller argument can supply or reuse that authority. Registry child-task
dispatch consumes the same ticket and cannot replay it.

Live bodydetails wraps microversionId as BTMicroversionId-366/theId. Feature IDs
use the separate underscore/hyphen-capable feature grammar. Feature-spec nodeId
values are freshly generated per GET and are excluded from specification hashing;
CAD entity identities remain included. Explicit incomplete feature trees refuse.
Sketch readback accepts validated disableImprinting=false and understood asVersion
metadata alongside sketchPlane, and refuses construction geometry.

## Assembly face connectors and fastened mates

`onshape.create_face_mate_connector` requires document_id, element_id,
instance_id, face_id and name (printable1..120); workspace_id is optional.
instance_id uses bounded JSON-only `[A-Za-z0-9_+/-]{1,128}` and is never a URL
segment. It must exactly identify one observed root Part instance in the target
assembly's default configuration. Nested assemblies/configuration overrides are
unsupported in this first slice. Donor document/element/part/microversion come
from that instance, never caller values. Before donor API reads, its document must
be present in the trusted project `_documents` menu supplied by the tool wrapper;
absence refuses. The public schema cannot supply this menu. Read bodydetails at
the immutable donor microversion and resolve exactly one actual planar face.

POST the existing v6 assembly `/features` endpoint with BTMMateConnector-66,
featureType=mateConnector; originType enum `Origin type`=ON_ENTITY;
originQuery BTMParameterQueryWithOccurrenceList-67 containing
BTMInferenceQueryWithOccurrence-1083, inferenceType=CENTROID, path=[instance_id],
deterministicIds=[face_id]. Use published occurrence structure; no custom query,
FeatureScript, raw payload, caller URL or caller donor source.

`onshape.create_fastened_mate` requires document_id, element_id, name and two
distinct first_connector_id/second_connector_id; workspace_id is optional.
Resolve both IDs to existing healthy assembly-local mateConnector features.
POST BTMMate-64, featureType=mate, version2; mateType enum `Mate type`=FASTENED;
mateConnectorsQuery is a query-with-occurrence list of two
BTMFeatureQueryWithOccurrence-157 records with those featureIds and path=[]
(the published assembly-local occurrence structure).

Both tools read target root assembly and feature-tree microversions, require
complete healthy observations and matching version, validate live built-in
specification types, and present the target identities, root state fingerprint,
actual selected geometry/connectors, and operation. Feature grammar permits
underscore/hyphen; document grammar remains separate. Only execution-relevant
validated specification fields and stable defaults bind the spec fingerprint;
per-request generated spec nodeIds are not CAD identity.

Complete previews and single-use trusted observation binding are mandatory.
Execution rechecks that binding before a sourceMicroversion/rejectMicroversionSkew
POST. Return only actual new healthy feature IDs after readback verifies their
requested relationships. An uncertain POST or post-read never triggers mutation
replay; return mutation_unverified. Existing graph-sync hook handles success.
No new route, shared contract, or UI flow is introduced.

## Variable Studio whole-table safety — SOLUSDEV-261

`get_variables` and the `set_variable` preview/write paths strictly validate every
vendor table and variable. Invalid collection shapes, missing writable fields,
invalid names or duplicate names across tables refuse; no malformed entries are
silently dropped. Computed vendor result metadata is not sent as writable state.
The replacement payload preserves each observed name, type, expression and optional
description exactly, including an explicitly empty description.

Because the variable POST replaces the entire table, the complete approval preview
contains each full before/after writable definition, including unchanged variables.
A table that cannot fit 40 rows with each field at most 400 characters is refused
rather than truncated. The existing fresh-preview gate detects any changed table
state before dispatch. A single-use task-local observation binding also requires
the complete freshly reread table to match immediately before POST, including
when central Build policy executes without a card. This is not an atomic vendor
compare-and-swap guarantee.

The Variable Studio replacement endpoint may return HTTP 204 with an empty body.
Accept that response only on this endpoint; do not require JSON or infer success
from it. Other POST decoders retain their existing JSON requirements.

After POST, read the complete table again and verify all writable definitions match
the proposed replacement, ignoring response order and computed values. A mismatch,
malformed response or failed post-write read returns `mutation_unverified`, explicitly
saying the update may have been applied and must be inspected before retrying.
Only verified readback is reported as a successful variable update.

## Assembly insertion binding — SOLUSDEV-261

Insertion reuses a single complete preview row builder for target identity and
microversion, pinned donor identity and its immutable microversion. A task-local
one-use binding must match those freshly reread rows immediately before POST.
Missing or changed bindings refuse without a write. Existing strict readback still
requires exactly one new healthy matching instance; uncertain outcomes cannot be
retried automatically. Both documents remain project-scoped. The vendor insertion
endpoint does not supply an atomic compare-and-swap guarantee against concurrent
external assembly changes.

## Existing feature edit binding — SOLUSDEV-261

Parameter updates share a normalized plan for previews and execution. Bind the
Part Studio and feature identity, source microversion, semantic feature tree,
and complete proposed parameter set. Generated node IDs and top-level transport
serialization version do not identify CAD state; the fresh version envelope is
still sent with rejectMicroversionSkew. Human rows retain each requested change.
A single-use observation must match immediately before POST. Fresh readback must
show the expected authored parameters and healthy feature state. Failed or
mismatched post-write observation returns an uncertain, nonretryable result;
it never silently repeats a mutation.

## Geometry-aware post-write graph sync — SOLUSDEV-261

The existing shared STEP/XCAF parser now measures each node's `geometry` attrs:
part-local bounding-box minimum, maximum and dimensions in millimetres, surface
area in square millimetres, and closed-solid volume in cubic millimetres (null
when no valid solid volume is available). STEP transfer units are explicitly
millimetres; measurements are rounded to nine decimal places. These are actual
OCCT measurements, not estimates from names or a byte digest. Existing assembly
hierarchy and occurrence placement edges are preserved. A bounding box is local
to its parsed product; it is not a world-space collision or mating proof.

Onshape document and part entities also retain `observed_microversion`, using the
same observation that keys the export cache and source cursor. A sketch-only
revision can change provenance without changing geometry; an interior cut can
change measured volume while leaving the outer bounding box unchanged. Successful
write-triggered sync therefore records the new revision and its geometry through
the normal graph ingestion path. These summaries do not encode the complete BREP
or prove every geometrical difference distinguishable. No new route or entity
kind is introduced.

Existing sources upgrade without a CAD edit: successful Onshape sync cursors carry
`projection_version: "cad-geometry-v3"`. After normal document selection and
microversion checks, an older or missing marker triggers one reingestion of a
nonempty tracked selection. Unreachable/quota-limited probes retain their existing
refusal policy. Only verified `revision-v2-*` payload entries can be reused and are parsed by
the current shared parser. Older cache associations are not reused. Only successful ingestion persists the new marker;
subsequent unchanged revisions skip normally. Empty selections remain idle.

A source's `syncing` lifecycle state retains its existing live Onshape tool
capability, including credential-refresh admission. A graph-refresh job is not
account revocation. `pending`, `error` and `disconnected` sources remain refused;
account status must still be connected, with current credentials, project document
selection and write access checked independently. This lets a verified CAD edit's
follow-up read run while its graph-sync job is in flight.


### Generic feature creation readback (SOLUSDEV-261)

`onshape.add_feature` reports success only after a fresh feature-tree read finds
exactly one created feature matching the returned ID, requested name and type,
with healthy active vendor state. Its successful result includes `verified: true`.
Missing/malformed identity, unhealthy or absent readback and transport failures
after write dispatch return `mutation_unverified`; callers must inspect current
state rather than replaying the write. This verifies identity and feature health,
not arbitrary parameter equivalence or resulting geometry acceptance.


### Verified revision acquisition and feature specifications (T1/T2)

Element discovery reads `/api/v6/documents/d/{did}/m/{revision}/elements`;
part metadata reads `/api/v6/parts/d/{did}/m/{revision}/e/{eid}`. Validate revision
identity before cache lookup or URL construction. The documented translation
surface supports workspace/version paths, so workspace STEP acquisition uses two
fresh uncached `currentmicroversion` reads: before translation submission and after
its completed download. Both must equal the planned revision. Drift refuses the
complete snapshot without publishing that export cache entry or automatically
retrying. Positive immutable empty-geometry proof remains required for an empty
export and is covered by the same bracket.

The `revision-v2-*` payload namespace excludes older potentially misassociated
entries. `cad-geometry-v3` triggers one repair ingestion for existing nonempty
tracked sources even without a CAD edit; only successful ingestion persists it.
This costs two additional revision GETs per cold export, including empty exports;
verified warm exports need no bracket calls. Existing element/record/byte bounds,
account isolation and complete-snapshot semantics remain unchanged.

`immutable_feature_specs` uses the documented Part Studio or Assembly
`/d/{did}/m/{revision}/e/{eid}/featurespecs` route. The caller first reads a fresh
feature tree and supplies its validated `sourceMicroversion`. Six production sites
use it: `_get_feature_specs`, `_preview_add_feature`, `_add_feature`, sketch
observation, cut observation, and mate observation. Cache identity includes
account, document, element, revision, collection and default configuration. Error,
partial, malformed parameter collections, invalid numeric metadata and nonfinite
JSON values are refused before caching; the existing parameter validator remains
authoritative. Custom configurations are not introduced by this interface.

Standalone spec reads and add previews each gain one fresh tree GET. Generic add
moves its existing prewrite tree read before spec acquisition; it retains mandatory
postwrite readback. Sketch/cut/mate reuse their existing fresh tree observations.
An unchanged repeated preview reuses its immutable spec GET while refreshing target
state; a new revision, account or collection misses the spec cache. Approval binding,
stale-state refusal and uncertain-write/no-replay behavior are unchanged.

### Explicit revolute mates (SOLUSDEV-261, additive native operation)

`onshape.create_revolute_mate` accepts the same assembly identity, name and two
distinct local connector feature IDs as `onshape.create_fastened_mate`. It creates
the built-in `mate` feature with `mateType=REVOLUTE`, retaining one rotational
degree of freedom. The live assembly specification must explicitly admit that
enum. Existing fastened semantics remain unchanged. This is a REST exception:
the admitted hosted inventory has no equivalent assembly-mating operation.

Both connector features must be healthy and local to the observed default-config
assembly. Fresh matching root/tree revisions, immutable selected specification,
state-bound preview, normal execution-policy admission and authoritative feature
readback remain mandatory. No arbitrary vendor payload is accepted. The preview
names both connectors, the revolute constraint and the primary/secondary alignment.
Revolute admission requires independently observed coaxial connector frames on
distinct occurrences. Opposite Z axes select the native primary-axis flip;
same-direction axes leave it disabled. With no `axial_offset_m`, their centers must
already coincide within `1e-8` m. A supplied finite offset (bounded to 500 m) must
agree within `1e-8` m with the measured pose-preserving value:
`dot(first_origin - second_origin, first_world_z)`. The native quantity uses that
measured value in meters, with `mateOffsetEnabled` set for a nonzero offset and
the live specification explicitly admitting `mateOffsetDistanceZ` as LENGTH.
Nonparallel primary axes are refused. Connector order, actual frames, the measured
flip and the measured offset bind
the preview. Limits and functional connections remain disabled; no physical servo
limits are invented. Readback verifies the actual new feature, REVOLUTE enum,
connector references, flags, offset and healthy regeneration, then independently
verifies every occurrence path and pose against the prewrite state. Movement or
missing evidence returns `mutation_unverified`; the operation is never replayed or
automatically undone.

This operation does not ground an assembly or create shaft-axis connectors.
Connector creation separately resolves verified root or nested occurrence paths.
The presence of a healthy mate alone does not prove complete mechanism
motion, clearance or freedom from overconstraints.

### Rigid mate pose preservation and correction (SOLUSDEV-261)

`create_fastened_mate` measures complete native connector frames before admission.
Origins must coincide, primary axes must be antiparallel, and the measured second
basis must match the first under one of the live admitted secondary alignments
PLUS_X, MINUS_X, PLUS_Y or MINUS_Y with `primaryAxisAlignment=true`.
The measured alignment is used rather than assuming PLUS_X. Arbitrary rotation,
translation and offsets are refused. The preview binds the full frames and
alignment, and fresh postwrite readback must retain all occurrence paths and
transforms within `1e-8`. Feature health alone is not proof of unchanged pose.
The compact assembly feature view exposes measured world X and Y axes alongside
the existing origin and Z axis, so SOL can assess rigid orientation.

Known quota refusals during complete-preview construction retain a fixed,
actionable conservation/exhaustion message through Build and confirmation gates.
They still return `unavailable` and cannot authorize execution. This treatment is
preview-only: a write whose subsequent readback fails remains uncertain and must
never claim that nothing executed. Generic exception text is not exposed.

`onshape.restore_fastened_pose` accepts document/workspace/assembly identity,
`feature_id` and `reference_microversion`. It corrects an existing healthy,
zero-offset FASTENED mate with flipped primary alignment by changing only its
secondary-axis alignment. It reads the historical assembly through the immutable
`/m/{reference_microversion}` path and verifies that current occurrence paths and
part/document/element identities still match. Expected same-document revision
advancement does not authorize changed identities or foreign revisions. The
current native local connector frames are evaluated under the historical poses;
the historical snapshot need not contain connectors added later. The resulting
frame measurement must select one of the admitted discrete secondary alignments.

The complete preview identifies the feature, historical reference and target
alignment, with fingerprints binding the current and historical states.
Execution uses the native
`POST .../features/featureid/{feature_id}` edit route with encoded opaque feature
identity and source-microversion skew rejection, retaining the feature ID, name,
references and every other parameter. Fresh readback must verify the edited
feature and all historical occurrence poses; uncertainty is never replayed or
automatically undone. Normal source/project/account authorization and reviewed
Build admission remain mandatory. This is a correction capability, not evidence
that an earlier failed autonomous placement succeeded.

### Complete-circle mate connectors (SOLUSDEV-261)

`onshape.create_circle_mate_connector` accepts document, workspace, assembly,
name, one root part instance ID or an `occurrence_path`, and one `edge_id`.
Exactly one occurrence selector is required; paths contain one to eight bounded
topology identifiers. It uses the native built-in
mate connector's `CENTER` inference on an independently observed complete
circular edge. Topology tokens remain bounded JSON identifiers; document,
workspace and element URL identifiers keep their existing stricter validation.
Nested paths resolve against exact, default-configuration assembly definitions
with tracked ancestor and donor documents. The complete path, ancestor revisions,
donor identity and measured world frame bind the preview. Root occurrence
transforms already represent world space and are not multiplied by parents again.
The native inference query and coordinate-system readback must use that exact
path. Arbitrary vendor parameters remain excluded.

Before preview or execution, verify a unique solid body and edge at the donor
microversion, finite positive radius, finite center, unit normal, complete circle
sweep and circumference, closed endpoints on the circle, and a proper rigid
occurrence transform. Derive the expected world center and axis from this
geometry. Fresh root/tree state and selected live built-in specification bind
the preview, which identifies the edge, expected center/axis and absence of
offsets or realignment. The normal Build policy applies.

After creating the connector, verify the new feature's query, flags and healthy
state, then independently read its assembly connector coordinate system. Resolve
its occurrence-relative frame with the corresponding observed rigid transform;
the resulting origin must match the measured circle center and its primary axis
must be parallel to the measured circle normal within explicit numerical
tolerances. Missing, ambiguous or inconsistent coordinate-system evidence returns
`mutation_unverified`, with no replay. A successful POST alone is insufficient.
Creating a connector must not reposition existing occurrences.

Geometry uses SI meters. Reject booleans as numbers, nonfinite values, reflected
or scaled transforms and non-affine matrices. Circle sweep/circumference use
relative tolerance `1e-6`, with length/closure absolute tolerance `1e-10` m;
world-origin and pose translation tolerance is `1e-8` m and unit-axis/rotation
tolerance is `1e-8`. Verify a full right-handed orthonormal returned frame. Its
primary axis may be antiparallel to the analytic edge normal for connector
verification, but return the actual signed axis; live mating requires compatible
measured directions rather than assuming the sign. Coordinate-system readback
must uniquely match the created feature ID and exact occurrence path, at the
same postwrite microversion as feature verification. Compare complete pre/post
occurrence path sets and transforms by path, independent of list order.

Live joint acceptance additionally compares both verified connector axes and
origins before mating, and checks all occurrence poses after the mate. This
proves the selected joint and placement only; it does not establish an entire
mechanism's grounding, travel limits or collision clearance.

### Compact assembly geometry for SOL inspection (SOLUSDEV-261)

`onshape.inspect_assembly_geometry` is a read-only operation accepting the usual
document/assembly/workspace identity, optional `instance_ids` (at most 16 unique
root instance IDs), `view` (`circles` or default `coincident_circles`), optional
nonnegative minimum/maximum radius in meters, `offset`, `limit` (1..10), and
`expected_snapshot`. Unknown or inconsistent arguments are rejected. It returns
geometric observations, never recommended mate types, selected joints or motion
limits. SOL must interpret the observations and independently verify writes.

Read one fresh default-config root assembly, then deduplicate its immutable donor
body requests by document/element/microversion. Every donor must be tracked and
authorized before fetching; do not silently inspect untracked donor documents.
Bound an unfiltered request to 64 root instances, 4 distinct donor payloads and
2000 complete-circle primitives; refuse oversized work with guidance to filter
instances. Nested, suppressed and configured occurrences are explicitly excluded,
not presented as inspected. Validate unique identities, matching revisions,
finite analytic geometry and proper rigid occurrence transforms. Reuse the
complete-circle geometry validation used by connector creation.

Return complete, bounded pages below the existing 3000-character model-containment
limit, accounting for escaping/redaction. Each observation includes instance/body/
edge identity, world center, signed normal and radius (SI meters), with enough
donor identity to locate the geometry. The coincident view groups circles from
different instances whose centers agree within `1e-8` m and whose unit normals
are parallel within `1e-8`; it reports measured members and does not assert that
they form a mechanical joint. Absence of a group does not establish absence of a
joint. Preserve whole observations; a single oversized observation refuses rather
than truncating identity. Include effective workspace, root revision, coverage,
total/offset/next_offset and a snapshot fingerprint covering the fresh root, donor revision identities,
complete validated circle observations and filters. Continuation requires the same fingerprint; changed root,
donor or query refuses. Mutable root observations are never served from cache.

This supplies numerical CAD evidence to SOL through the existing tool seam.
It does not claim that SOL received an image or screenshot.

### Large immutable donor inspection payloads (SOLUSDEV-261)

Immutable donor geometry may be acquired and validated up to 32 MiB of serialized
JSON; feature specifications retain their 8 MiB bound. Cache storage retains its
8 MiB per-entry ceiling. A valid donor above that storage ceiling is returned
without caching, rather than failing inspection. Requests above the acquisition
ceiling fail with a specific size diagnostic, never an assertion that the CAD
topology is malformed. Account isolation, immutable revision validation and all
compact output/primitive bounds remain unchanged. This does not claim large
donors are cached or that subsequent calls avoid refetching them.

Assembly inspection continuation fingerprints retain the full fresh root and
exact validated circle observations, donor revisions, effective workspace and
filters. Unused donor face-area metadata is excluded; no geometric rounding is
introduced. Circle, pose, revision and filter changes still invalidate pages.
Geometry and assembly-feature identities used only as JSON values accept the
vendor's bounded `+` and `/` tokens; resource URL identities stay strict.

A fresh export-revision mismatch invalidates only that account/document's mutable
change signal, then refuses the current snapshot unchanged. It never retries an
export automatically. The next normal sync must reacquire its plan instead of
reusing a proven-stale signal. Immutable payload caches remain untouched.

Native tool authority may survive the exact server-owned `revision_changed`
source error while the connected account and grant remain valid. Both initial
source selection and refresh admission use the same narrow predicate; other
error/disconnected states remain refused. This does not mark the graph current
or clear its sync error.

### Bounded assembly feature readback (SOLUSDEV-261)

The existing `onshape.get_assembly_definition` accepts optional `view=features`,
`offset`, `limit` (1..10), and `expected_snapshot` required after offset zero.
Omitting the view preserves the existing response for compatibility. The feature
view reads fresh root assembly and assembly feature tree at matching revisions,
then returns complete model-sized pages below 3000 contained characters. Rows
include feature identity, name, type, suppression and explicit observed feature
health. Mate connector rows additionally expose exact occurrence path and actual
world-space coordinate frame derived from the vendor connector CS and validated
occurrence transform. Missing or malformed required frame evidence refuses,
never invents a frame or declares an unobserved feature healthy.

Pages include effective workspace, root revision, total, offset, next offset and
a snapshot bound to the complete validated feature observations and their fresh
root state. Revision, pose or feature changes invalidate continuation. Complete
rows are retained; an oversized single row refuses instead of truncating. No
write, grant, graph-freshness or numeric model-budget behavior changes. The
operation description tells SOL to use this view for feature and mate readback.

### Nested and coaxial assembly observations (SOLUSDEV-261)

`inspect_assembly_geometry` additionally accepts `include_nested` (default false)
and `view=coaxial_circles`. Nested inspection resolves exact occurrence paths
through the fresh root response's revision-matched subassembly definitions;
all ancestor and donor documents must be tracked. Default configurations only,
maximum path depth 8, 256 occurrence records and 64 inspected leaf parts; existing
four-donor/2000-circle limits remain. Root instance filters select their subtrees.
Outputs include exact occurrence paths and use the observed root-space leaf
transform, never multiply that transform by its parent again.

Coaxial observations report pairs from different occurrences whose measured
circle-axis lines agree within the existing geometric tolerance, even when their
centers differ along the axis. Each line/occurrence pair returns the pair of
observed circles with the smallest axial separation, with deterministic tie
breaking, and reports that separation. This is a geometric representative, not a
joint recommendation. Bound pair generation to 2000 and preserve complete pages.
SOL must still choose mate types from geometry and intended motion; these reads
never create connectors, guess mechanical roles, or authorize a nested write.

Circle observations include `occurrence_name`, the exact vendor occurrence label
when it is a printable string of at most 200 characters, otherwise null. Labels
remain untrusted descriptive data and are never inferred from geometry or used
as authority. They are bound into the observation snapshot and the existing
whole-page size limit still applies.


## ADR-038 — SOL reads through the mirror (SOLUSDEV-312)

- Agent tool connectors are built with `purpose="agent"` (deferrable) and a
  metering label: `agent_read` for reads, `agent_write` for writes and their
  previews/readbacks.
- One SOL turn = one tool registry = one `TurnReadMemo` (entries also expire
  after 60 s). Within a turn each `(account, document)` costs at most ONE
  `currentmicroversion` probe; reads then use immutable `/m/{mv}` paths cached in
  the integration cache (`mirrored_get`). Incomplete or error payloads are never
  cached.
- `workspace_for` uses the workspace recorded on the source cursor
  (`cursor["workspaces"]`) before falling back to one `GET /documents/{d}` per
  turn; a stale recorded workspace heals once.
- Preview cards name the document from the turn memo → graph document node →
  cached listing → id, with no provider call.
- `list_documents` serves from the account's cached listing (the pickers' cache);
  `refresh=true` walks the provider, bounded by the listing cooldown and the
  10-page limit.
- **Writes are unchanged in their safety properties:** live pre-write read,
  `sourceMicroversion` + `rejectMicroversionSkew`, mandatory readback,
  `mutation_unverified` on doubt. A write retires that document's memoised probe
  (even on failure), so the next read re-probes.
- Measured (tests): a Guide turn of four reads on one synced document costs 5
  requests cold and 1 warm (was 8); a two-write Build turn costs 10 (was 20).
