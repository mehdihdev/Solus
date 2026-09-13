/** Parsing and validation helpers for the waitlist endpoint. */

// RFC 5321 caps a forward path at 254 characters.
export const MAX_EMAIL_LENGTH = 254;

// Enough for any legitimate payload; anything larger is rejected unread.
export const MAX_BODY_BYTES = 2_048;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email) {
  return email.length <= MAX_EMAIL_LENGTH && EMAIL_PATTERN.test(email);
}

/**
 * Vercel terminates TLS at the edge and forwards the caller in x-forwarded-for.
 * The left-most entry is the client; the rest are proxies.
 */
export function getClientKey(request) {
  const forwarded = request.headers.get("x-forwarded-for");

  if (forwarded) {
    const [first] = forwarded.split(",");

    if (first?.trim()) {
      return first.trim();
    }
  }

  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

/**
 * Reads the JSON body with a hard size cap, so an oversized payload is rejected
 * rather than buffered.
 *
 * @returns {Promise<{ ok: true, value: object } | { ok: false, reason: string }>}
 */
export async function readJsonBody(request) {
  const declaredLength = Number(request.headers.get("content-length"));

  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    return { ok: false, reason: "too-large" };
  }

  let raw;

  try {
    raw = await request.text();
  } catch {
    return { ok: false, reason: "unreadable" };
  }

  if (raw.length > MAX_BODY_BYTES) {
    return { ok: false, reason: "too-large" };
  }

  try {
    const parsed = JSON.parse(raw);

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, reason: "not-an-object" };
    }

    return { ok: true, value: parsed };
  } catch {
    return { ok: false, reason: "malformed-json" };
  }
}
