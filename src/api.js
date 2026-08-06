/**
 * Client-side API wrapper for Claude Search Library.
 *
 * All requests go to the same origin the page was served from (the local
 * Flask server), so no base URL configuration is needed.
 */

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch (e) {
    // No JSON body (e.g. a network-level failure) - fall through with body=null.
  }

  if (!response.ok) {
    const message = (body && body.error) || `Request to ${path} failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    // A 401 from anything other than /setup itself (wrong-credentials
    // there is a normal, expected 401, not an expired session) means the
    // server-side session cookie is missing or expired - which can now
    // happen independently of the client's own "unlocked" flag (that
    // flag has no expiry of its own). Without this, the UI would keep
    // rendering as if unlocked while every API call silently 401s.
    // window.dispatchEvent (not a direct call) so this plain script file
    // doesn't need a React import to notify the app.
    if (response.status === 401 && path !== "/setup") {
      window.dispatchEvent(new CustomEvent("csl:session-expired"));
    }
    throw error;
  }

  return body;
}

/**
 * Verify passphrase + TOTP code against the server's existing setup.
 *
 * The server never returns an encryption key - this call is authentication
 * only. Return shape: { success: bool, error?: string }.
 */
async function setup(passphrase, totpCode) {
  try {
    const result = await request("/setup", {
      method: "POST",
      body: JSON.stringify({ passphrase, totp_code: totpCode }),
    });
    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

/**
 * Invalidate this browser's session server-side (the session cookie
 * /setup issues on success). Locking used to only clear client-side
 * storage, leaving the actual server-side session valid until it expired
 * on its own - this makes Lock a real server-enforced action.
 */
async function logout() {
  try {
    await request("/logout", { method: "POST" });
  } catch (error) {
    // Best-effort - the client-side lock (clearing localStorage) still
    // happens regardless of whether this call succeeds.
  }
}

function buildSearchParams(query, options = {}) {
  const params = new URLSearchParams({ q: query });
  if (options.top_k) params.set("top_k", String(options.top_k));
  if (options.mode) params.set("mode", options.mode);
  // options.filters is the {source, device, tags, date_range} shape
  // src/search.py expects - it must travel as one JSON-encoded param
  // (not flattened into individual query keys) since date_range/tags
  // are structured, not scalar.
  if (options.filters && Object.keys(options.filters).length > 0) {
    params.set("filters", JSON.stringify(options.filters));
  }
  return params;
}

/**
 * Run a search against the /search endpoint.
 * `options`: {top_k, mode, filters}. Returns the array of result objects
 * (not the wrapping envelope).
 */
async function search(query, options = {}) {
  const params = buildSearchParams(query, options);
  const data = await request(`/search?${params.toString()}`);
  return data.results || [];
}

/** Fetch full session + summary details by session id. */
async function getSession(sessionId) {
  return request(`/session/${encodeURIComponent(sessionId)}`);
}

/** Fetch system-wide stats (session counts, sync status, etc). */
async function getStats() {
  return request("/stats");
}

/** Fetch the list of devices known to sync_metadata. */
async function getDevices() {
  const data = await request("/devices");
  return data.devices || [];
}

/** Approve (or reject) a session flagged for manual review. */
async function approveReview(sessionId, approved, notes = "") {
  return request(`/review/${encodeURIComponent(sessionId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved, notes }),
  });
}

/** Fetch archive integrity status (healthy/unhealthy + stats). Check before syncing. */
async function getHealth() {
  // /health intentionally returns HTTP 503 when unhealthy (so tools like
  // curl/monitoring see failure at the transport level), but the JSON body
  // - {healthy, errors, warnings, stats} - is the real payload callers want
  // either way. request() throws on non-2xx and would otherwise discard it.
  try {
    return await request("/health");
  } catch (err) {
    if (err.body) return err.body;
    throw err;
  }
}

/**
 * Trigger a push/pull/bidirectional sync.
 *
 * Passphrase + TOTP code are required on every call - the server never
 * caches the derived encryption key between requests (see server.py's
 * /sync docstring for why: it binds 0.0.0.0 for LAN/phone access, so a
 * cached key would let anyone on the same network trigger a sync without
 * ever proving they know the passphrase or a live TOTP code).
 *
 * Returns {direction, files_changed, conflicts, reindexed}.
 */
async function sync(passphrase, totpCode, direction = "bidirectional") {
  return request("/sync", {
    method: "POST",
    body: JSON.stringify({ passphrase, totp_code: totpCode, direction }),
  });
}

/**
 * Import one or more already-exported Claude.ai conversation JSON objects
 * (the shape produced by Settings -> Export data) without the user
 * manually placing files in raw_exports/claude-ai/. Does not trigger
 * collection itself - the next `cli.py collect` picks these up.
 *
 * Returns {imported: number, files: string[]}.
 */
async function importSessions(sessions) {
  return request("/import", {
    method: "POST",
    body: JSON.stringify({ sessions }),
  });
}

/**
 * Upload a claude.ai Data Export file (the ZIP from Settings -> Export
 * data, or a bare conversations.json) for server-side conversion via
 * src/claude_export_import.py — handles the real official export schema
 * (uuid/name/chat_messages[]/sender/text), not just pre-normalized JSON.
 *
 * Returns {converted: number, skipped: number, files: string[]}.
 */
async function importExport(file) {
  const formData = new FormData();
  formData.append("file", file);
  // Don't set Content-Type manually - the browser must set the multipart
  // boundary itself, so this bypasses request()'s default JSON header.
  const response = await fetch("/import-export", { method: "POST", body: formData });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = (body && body.error) || `Request to /import-export failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

/** Fetch API spend, optionally scoped to a month ("YYYY-MM") or quarter ("YYYY-QN"). */
async function getCosts(options = {}) {
  const params = new URLSearchParams();
  if (options.month) params.set("month", options.month);
  if (options.quarter) params.set("quarter", options.quarter);
  const qs = params.toString();
  return request(`/costs${qs ? `?${qs}` : ""}`);
}

/** Fetch sessions currently stuck in needs_review. */
async function getNeedsReview() {
  const data = await request("/review");
  return data.sessions || [];
}

/** Re-run summarization + indexing for failed sessions. Omit sessionIds to reprocess all needs_review sessions. */
async function reprocessReview(sessionIds) {
  // Server requires "confirm": true whenever session_ids is omitted (see
  // server.py's reprocess_review_endpoint docstring, R-2) - the "Reprocess
  // All" button that drives this path already shows the pending count on
  // screen before it's clickable, so that's the confirmation.
  return request("/review/reprocess", {
    method: "POST",
    body: JSON.stringify(
      sessionIds && sessionIds.length ? { session_ids: sessionIds } : { confirm: true }
    ),
  });
}

/** Fetch other sessions sharing tags with the given session. */
async function getRelated(sessionId) {
  const data = await request(`/session/${encodeURIComponent(sessionId)}/related`);
  return data.related || [];
}

// Exposed as a global for the CDN-based React app (public/index.html) and
// as CommonJS exports for anything that runs under Node/Jest.
const api = {
  setup, logout, search, getSession, getStats, getDevices, approveReview,
  getHealth, sync, importSessions, importExport, getCosts,
  getNeedsReview, reprocessReview, getRelated,
};

if (typeof window !== "undefined") {
  window.ClaudeSearchAPI = api;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
