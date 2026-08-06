/**
 * Tests for src/api.js - the fetch wrapper the CDN-based React app
 * (public/index.html) calls. Only this file is covered: it's plain,
 * DOM-free JS with real dual Node/browser exports already built in
 * (see its own bottom comment) - public/index.html's React components
 * themselves have no build step and no existing harness to run them
 * under, so they stay covered by manual verification (see
 * CHANGELOG.md's Design Critic pass) rather than gaining one here.
 *
 * Uses Node's built-in test runner (`node --test`), not a third-party
 * framework - this project deliberately has no npm dependency tree for
 * the frontend (public/index.html loads React from a CDN, no bundler),
 * so pulling in Jest/Vitest just for this one file would be a bigger
 * footprint than the thing being tested.
 */
const assert = require("node:assert/strict");
const { test, beforeEach, afterEach } = require("node:test");

const api = require("../../src/api.js");

let originalFetch;
let originalWindow;
let fetchCalls;
let nextResponse;

beforeEach(() => {
  originalFetch = global.fetch;
  originalWindow = global.window;
  fetchCalls = [];

  // Minimal window shim so api.js's window.dispatchEvent/CustomEvent
  // path (the 401 session-expiry signal) is exercisable under plain
  // Node, without pulling in jsdom for one event.
  global.window = {
    _listeners: {},
    addEventListener(type, cb) {
      (this._listeners[type] ||= []).push(cb);
    },
    dispatchEvent(event) {
      for (const cb of this._listeners[event.type] || []) cb(event);
    },
  };
  global.CustomEvent = class CustomEvent {
    constructor(type, opts) {
      this.type = type;
      this.detail = opts && opts.detail;
    }
  };

  global.fetch = async (path, options) => {
    fetchCalls.push({ path, options });
    return nextResponse;
  };
});

afterEach(() => {
  global.fetch = originalFetch;
  global.window = originalWindow;
});

function mockResponse({ ok = true, status = 200, body = {} } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

// --- search() / buildSearchParams --------------------------------------

test("search sends q and returns the results array, not the envelope", async () => {
  nextResponse = mockResponse({ body: { results: [{ session_id: "a" }] } });

  const results = await api.search("minecraft");

  assert.equal(fetchCalls[0].path, "/search?q=minecraft");
  assert.deepEqual(results, [{ session_id: "a" }]);
});

test("search returns [] when the server response has no results key", async () => {
  nextResponse = mockResponse({ body: {} });
  const results = await api.search("anything");
  assert.deepEqual(results, []);
});

test("search encodes filters as a single JSON query param, not flattened keys", async () => {
  nextResponse = mockResponse({ body: { results: [] } });

  await api.search("x", { top_k: 5, mode: "hybrid", filters: { source: "vscode" } });

  const url = new URL(fetchCalls[0].path, "http://localhost");
  assert.equal(url.searchParams.get("top_k"), "5");
  assert.equal(url.searchParams.get("mode"), "hybrid");
  assert.equal(url.searchParams.get("filters"), JSON.stringify({ source: "vscode" }));
});

test("search omits the filters param entirely when filters is empty", async () => {
  nextResponse = mockResponse({ body: { results: [] } });
  await api.search("x", { filters: {} });
  const url = new URL(fetchCalls[0].path, "http://localhost");
  assert.equal(url.searchParams.has("filters"), false);
});

// --- request()'s error handling -----------------------------------------

test("a non-2xx response throws an Error carrying status and body", async () => {
  nextResponse = mockResponse({ ok: false, status: 404, body: { error: "not found" } });

  await assert.rejects(
    () => api.getSession("missing"),
    (err) => {
      assert.equal(err.message, "not found");
      assert.equal(err.status, 404);
      assert.deepEqual(err.body, { error: "not found" });
      return true;
    }
  );
});

test("falls back to a generic message when the error body has no 'error' field", async () => {
  nextResponse = mockResponse({ ok: false, status: 500, body: {} });
  await assert.rejects(() => api.getStats(), /failed with status 500/);
});

test("a 401 from any endpoint other than /setup dispatches csl:session-expired", async () => {
  nextResponse = mockResponse({ ok: false, status: 401, body: { error: "unlock required" } });
  let fired = false;
  window.addEventListener("csl:session-expired", () => {
    fired = true;
  });

  await assert.rejects(() => api.getStats());

  assert.equal(fired, true);
});

test("a 401 specifically from /setup does NOT dispatch csl:session-expired (it's a normal wrong-credentials response)", async () => {
  nextResponse = mockResponse({ ok: false, status: 401, body: { error: "invalid passphrase" } });
  let fired = false;
  window.addEventListener("csl:session-expired", () => {
    fired = true;
  });

  const result = await api.setup("wrong-pass", "000000");

  assert.equal(fired, false);
  assert.equal(result.success, false);
});

// --- setup() ---------------------------------------------------------------

test("setup() never throws - failures resolve to {success: false, error}", async () => {
  nextResponse = mockResponse({ ok: false, status: 401, body: { error: "invalid TOTP code" } });
  const result = await api.setup("pass", "111111");
  assert.deepEqual(result, { success: false, error: "invalid TOTP code" });
});

test("setup() success returns {success: true, ...serverResponse}", async () => {
  nextResponse = mockResponse({ body: {} });
  const result = await api.setup("pass", "222222");
  assert.equal(result.success, true);
});

// --- reprocessReview()'s confirm-flag logic --------------------------------
// Regression coverage for a real server-side requirement (server.py's R-2
// fix): omitting session_ids means "reprocess everything", which now
// requires confirm:true. This client function is the only place that
// requirement is actually satisfied on the caller's behalf.

test("reprocessReview with explicit session_ids sends those ids, no confirm flag", async () => {
  nextResponse = mockResponse({ body: { succeeded: [], failed: [], needs_review: [] } });
  await api.reprocessReview(["a", "b"]);
  const sentBody = JSON.parse(fetchCalls[0].options.body);
  assert.deepEqual(sentBody, { session_ids: ["a", "b"] });
});

test("reprocessReview with no session_ids sends confirm:true instead", async () => {
  nextResponse = mockResponse({ body: { succeeded: [], failed: [], needs_review: [] } });
  await api.reprocessReview(null);
  const sentBody = JSON.parse(fetchCalls[0].options.body);
  assert.deepEqual(sentBody, { confirm: true });
});

test("reprocessReview with an empty array behaves the same as null (confirm:true)", async () => {
  nextResponse = mockResponse({ body: { succeeded: [], failed: [], needs_review: [] } });
  await api.reprocessReview([]);
  const sentBody = JSON.parse(fetchCalls[0].options.body);
  assert.deepEqual(sentBody, { confirm: true });
});

// --- getHealth()'s 503-with-real-body handling -----------------------------

test("getHealth returns the JSON body even on a 503 (health endpoint's real payload)", async () => {
  nextResponse = mockResponse({ ok: false, status: 503, body: { healthy: false, errors: ["bad"] } });
  const result = await api.getHealth();
  assert.deepEqual(result, { healthy: false, errors: ["bad"] });
});

test("getHealth re-throws when a 503-like failure has no body at all", async () => {
  nextResponse = { ok: false, status: 503, json: async () => { throw new Error("no body"); } };
  await assert.rejects(() => api.getHealth());
});

// --- simple passthrough getters --------------------------------------------

test("getDevices returns [] when the server response has no devices key", async () => {
  nextResponse = mockResponse({ body: {} });
  assert.deepEqual(await api.getDevices(), []);
});

test("getNeedsReview returns [] when the server response has no sessions key", async () => {
  nextResponse = mockResponse({ body: {} });
  assert.deepEqual(await api.getNeedsReview(), []);
});

test("getRelated returns [] when the server response has no related key", async () => {
  nextResponse = mockResponse({ body: {} });
  assert.deepEqual(await api.getRelated("s1"), []);
});

// --- getCosts()'s optional query params ------------------------------------

test("getCosts with no options hits /costs with no query string", async () => {
  nextResponse = mockResponse({ body: {} });
  await api.getCosts();
  assert.equal(fetchCalls[0].path, "/costs");
});

test("getCosts scopes to a month when given", async () => {
  nextResponse = mockResponse({ body: {} });
  await api.getCosts({ month: "2026-08" });
  assert.equal(fetchCalls[0].path, "/costs?month=2026-08");
});
