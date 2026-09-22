# Account document tree — SOLUSDEV-261

Governs the additive folder browser in Workspace Add → Integrations. Existing
`GET /users/me/connections/{id}/documents` stays compatible for flat selectors.

`GET /api/v1/users/me/connections/{connection_id}/document-tree`
requires CurrentUser, RequireVerified, owner-only connection lookup and a connected
provider grant. It supports the Onshape connector; unsupported providers return 400.

Query: `node` is `root` (default), `shared`, `folder:<24 lowercase hex id>`, or
`owner:resourceuserowner:<24 lowercase hex id>` / `owner:resourcecompanyowner:<id>`.
`offset` is an integer 0–100000 (default 0). `refresh` and `cache_only` are booleans,
mutually exclusive. The provider page size is fixed at 20. Root navigation is not
paginated. Unsupported node kinds and malformed IDs are rejected before provider I/O.

Response envelope `data` contains `{items, next_offset}`. Each item contains `id`,
`name`, `kind` (`folder` or `document`), and `node` (folder navigation key, null for
a document). A document's id is the exact document id used by existing attachment
routes. Folders cannot be attached. `next_offset` is null or a strictly advancing
bounded integer parsed from a verified provider next URL. Metadata contains
`cached` and `fetched_at`, exactly like the existing account listing.

Pages are cached per provider/account/node/offset with I1 expiry, explicit refresh
cooldown, and single-flight. A cache-only miss is 409 listing_not_cached and never
resolves credentials or calls the provider. Errors never replace valid cache pages.
Account revocation invalidates these keys through I1's existing account index.

Onshape root navigation is acquired from `/api/globaltreenodes`; owner collections,
shared navigation (`magic/12`, verified live), and folder children use its returned
navigation model. These endpoints are live-verified on the user's account but are
not listed in the public OpenAPI. Vendor responses remain untrusted. Follow only
HTTPS URLs at the configured Onshape origin, bounded known navigation paths, and
validated advancing offsets; no arbitrary treeHref or next URL may direct a request.
Unexpected schemas fail clearly rather than inventing folders or hiding truncation.

Account-list responses add `document_tree: boolean`, derived from the connector's
`supports_document_tree` capability (false when absent), so the shared renderer
selects this browser without naming a vendor. Connector `list_document_tree`
implements the provider acquisition; the account route/service stays generic.
