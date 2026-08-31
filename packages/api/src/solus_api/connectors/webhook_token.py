"""Per-source webhook credentials (SOLUSDEV-167).

**The URL is the credential.** A provider notification arrives at
`/api/v1/webhooks/{provider}/{source_id}/{token}`, and the token — 256 bits,
minted at connect, stored only as a sha256 digest — is what authorizes it.

Why not match on the payload's document/repo id, which is the obvious design?
Because that identifier is GLOBAL. Two teams tracking the same shared Onshape
document, or the same GitHub repo, would both match one delivery; each would
then sync with its own credentials, and one tenant's edit would spend another
tenant's annual quota with no way for them to see why. A per-source URL resolves
to exactly one source by construction, so that cross-tenant fan-out cannot be
expressed.

It also solves a problem Onshape hands us: **Onshape publishes no inbound
signature scheme**, so the Stripe HMAC pattern does not transfer. With the URL as
the credential we need no vendor signature at all — and where a vendor does sign
(GitHub's `X-Hub-Signature-256`), that check is kept as defence in depth with a
per-source secret rather than one global one.

Replay is harmless: a captured delivery costs one debounced probe of a source the
holder could already trigger.

sha256 rather than a KDF, following `deps.panel_token_hash`: the token carries
256 bits of entropy, so there is nothing to slow down.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: `Source.config` key holding the digest. The `_` prefix is load-bearing:
#: `routers/sources.py` strips underscore-prefixed keys from config on BOTH
#: create and PATCH, so this can never be written — or overwritten — through the
#: API. Only server-side code can set it.
WEBHOOK_TOKEN_KEY = "_webhook_token_sha256"  # noqa: S105 — a key NAME, not a secret


def mint_webhook_token() -> tuple[str, str]:
    """A fresh (token, digest). The token is returned ONCE, to be handed to the
    provider at registration; only the digest is ever stored."""
    token = secrets.token_urlsafe(32)
    return token, webhook_token_digest(token)


def webhook_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, stored_digest: str | None) -> bool:
    """Constant-time compare. A source with no stored digest matches nothing —
    fail closed, so an unregistered source cannot be poked."""
    if not stored_digest:
        return False
    return hmac.compare_digest(webhook_token_digest(token), stored_digest)
