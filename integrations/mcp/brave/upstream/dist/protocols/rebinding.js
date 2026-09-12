import { isLoopbackHostname } from '../utils.js';
// 403 with a JSON-RPC error and no id, per the MCP Streamable HTTP spec.
const sendForbidden = (res, message) => {
    res.status(403).json({ jsonrpc: '2.0', error: { code: -32600, message }, id: null });
};
const stripBrackets = (hostname) => hostname.replace(/^\[|\]$/g, '').toLowerCase();
// Canonical origin ("scheme://host[:port]", lowercased with the default port
// dropped) or null when the value is not a parseable origin. Using URL.origin
// makes comparisons case- and default-port-insensitive.
export const canonicalizeOrigin = (value) => {
    const trimmed = value.trim();
    if (trimmed.length === 0)
        return null;
    try {
        const origin = new URL(trimmed).origin;
        // URL.origin may be 'null' for opaque origins, e.g. 'blob:'.
        return origin === 'null' ? null : origin;
    }
    catch {
        return null;
    }
};
/**
 * Returns the bare, lowercased hostname (port and IPv6 brackets removed), or
 * null when the value is not a clean "host[:port]". Parsing via URL rejects
 * malformed authorities (bad ports, embedded userinfo, paths, etc.) by
 * returning null so they fail closed.
 * @returns The canonicalized hostname, or null if the value is not a clean "host[:port]".
 * @example normalizeHost('example.com:8080') === 'example.com'
 * @example normalizeHost('example.com') === 'example.com'
 * @example normalizeHost('example.com/path') === null
 * @example normalizeHost('example.com?q=1') === null
 * @example normalizeHost('example.com#frag') === null
 * @example normalizeHost('example.com@user:pass') === null
 * @example normalizeHost('example.com:80evil') === null
 * @example normalizeHost('example.com:99999999') === null
 * @example normalizeHost('[::1]') === '::1'
 */
export const normalizeHost = (value) => {
    const trimmed = value.trim();
    if (trimmed.length === 0)
        return null;
    // A Host header carries only "host[:port]"; any path delimiter is malformed.
    if (trimmed.includes('/') || trimmed.includes('\\'))
        return null;
    let url;
    try {
        url = new URL(`http://${trimmed}`);
    }
    catch {
        return null;
    }
    // A Host header carries only "host[:port]"; anything else is malformed.
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
        return null;
    }
    return stripBrackets(url.hostname);
};
const toNormalizedSet = (values, normalize) => {
    const set = new Set();
    for (const value of values) {
        const normalized = normalize(value);
        if (normalized !== null)
            set.add(normalized);
    }
    return set;
};
const isOriginAllowed = (origin, allowedOrigins) => {
    const trimmed = origin.trim();
    if (trimmed.length === 0)
        return false;
    let url;
    try {
        url = new URL(trimmed);
        // URL.origin may be 'null' for opaque origins, e.g. 'blob:'.
        if (url.origin === 'null')
            return false;
    }
    catch {
        return false;
    }
    return isLoopbackHostname(stripBrackets(url.hostname)) || allowedOrigins.has(url.origin);
};
const isHostAllowed = (hostHeader, allowedHosts) => {
    const host = normalizeHost(hostHeader);
    if (host === null)
        return false;
    return isLoopbackHostname(host) || allowedHosts.has(host);
};
// Builds Express middleware that guards against DNS rebinding:
// - Origin is always validated. A request with no Origin header passes through
//   (non-browser MCP clients omit it), but any present Origin must be loopback
//   or explicitly allow-listed.
// - Host is validated only when allowedHosts is configured (opt-in), so
//   reverse-proxy / custom-domain deployments are unaffected by default.
export const createDnsRebindingGuard = (options) => {
    const allowedOrigins = toNormalizedSet(options.allowedOrigins, canonicalizeOrigin);
    const allowedHosts = toNormalizedSet(options.allowedHosts, normalizeHost);
    const enforceHost = allowedHosts.size > 0;
    return (req, res, next) => {
        const origin = req.headers.origin;
        if (origin !== undefined) {
            // Origin may be undefined (non-browser MCP clients omit it), but any
            // present Origin must be validated.
            if (typeof origin !== 'string' || !isOriginAllowed(origin, allowedOrigins)) {
                sendForbidden(res, 'Forbidden: invalid Origin');
                return;
            }
        }
        if (enforceHost) {
            // Host is validated only when allowedHosts is configured (opt-in), so
            // reverse-proxy / custom-domain deployments are unaffected by default.
            const host = req.headers.host;
            if (typeof host !== 'string' || !isHostAllowed(host, allowedHosts)) {
                sendForbidden(res, 'Forbidden: invalid Host');
                return;
            }
        }
        next();
    };
};
