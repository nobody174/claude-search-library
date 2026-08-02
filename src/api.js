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

function buildSearchParams(query, filters = {}) {
  const params = new URLSearchParams({ q: query });
  if (filters.top_k) params.set("top_k", String(filters.top_k));
  if (filters.mode) params.set("mode", filters.mode);
  return params;
}

/**
 * Run a search against the /search endpoint.
 * Returns the array of result objects (not the wrapping envelope).
 */
async function search(query, filters = {}) {
  const params = buildSearchParams(query, filters);
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
  return request("/health");
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

// Exposed as a global for the CDN-based React app (public/index.html) and
// as CommonJS exports for anything that runs under Node/Jest.
const api = {
  setup, search, getSession, getStats, getDevices, approveReview,
  getHealth, sync, importSessions,
};

if (typeof window !== "undefined") {
  window.ClaudeSearchAPI = api;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
