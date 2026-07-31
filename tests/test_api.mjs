// Lightweight test suite for src/api.js using Node's built-in test runner.
// Run with: node --test tests/test_api.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const path = require("path");

function loadApiWithFetch(fetchImpl) {
  // api.js attaches to `module.exports` when running under CommonJS/Node,
  // and reads the global `fetch` at call time - so we just need to stub it.
  global.fetch = fetchImpl;
  const apiPath = path.resolve(import.meta.dirname, "../src/api.js");
  delete require.cache[require.resolve(apiPath)];
  return require(apiPath);
}

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

test("setup() returns success on valid credentials", async () => {
  const api = loadApiWithFetch(async (path, options) => {
    assert.equal(path, "/setup");
    const body = JSON.parse(options.body);
    assert.equal(body.passphrase, "correct-horse");
    assert.equal(body.totp_code, "123456");
    return jsonResponse({ success: true });
  });

  const result = await api.setup("correct-horse", "123456");
  assert.equal(result.success, true);
});

test("setup() returns success:false with error message on 401", async () => {
  const api = loadApiWithFetch(async () =>
    jsonResponse({ success: false, error: "invalid TOTP code" }, { ok: false, status: 401 })
  );

  const result = await api.setup("wrong", "000000");
  assert.equal(result.success, false);
  assert.match(result.error, /invalid TOTP code/);
});

test("search() returns the results array, not the full envelope", async () => {
  const api = loadApiWithFetch(async (path) => {
    assert.match(path, /^\/search\?/);
    assert.match(path, /q=minecraft/);
    return jsonResponse({
      results: [{ session_id: "s1", title: "t" }],
      total_results: 1,
      query_time_ms: 12.3,
    });
  });

  const results = await api.search("minecraft");
  assert.deepEqual(results, [{ session_id: "s1", title: "t" }]);
});

test("search() includes top_k and mode in the query string when provided", async () => {
  let capturedPath;
  const api = loadApiWithFetch(async (path) => {
    capturedPath = path;
    return jsonResponse({ results: [] });
  });

  await api.search("async", { top_k: 5, mode: "keyword" });
  assert.match(capturedPath, /top_k=5/);
  assert.match(capturedPath, /mode=keyword/);
});

test("getSession() URL-encodes the session id and returns the body", async () => {
  const api = loadApiWithFetch(async (path) => {
    assert.equal(path, "/session/sess%2F1");
    return jsonResponse({ id: "sess/1", title: "t" });
  });

  const session = await api.getSession("sess/1");
  assert.equal(session.id, "sess/1");
});

test("getStats() returns the stats object", async () => {
  const api = loadApiWithFetch(async (path) => {
    assert.equal(path, "/stats");
    return jsonResponse({ total_sessions: 42 });
  });

  const stats = await api.getStats();
  assert.equal(stats.total_sessions, 42);
});

test("getDevices() returns the devices array, not the wrapping object", async () => {
  const api = loadApiWithFetch(async (path) => {
    assert.equal(path, "/devices");
    return jsonResponse({ devices: [{ device_id: "d1" }] });
  });

  const devices = await api.getDevices();
  assert.deepEqual(devices, [{ device_id: "d1" }]);
});

test("getDevices() returns an empty array when devices is missing", async () => {
  const api = loadApiWithFetch(async () => jsonResponse({}));
  const devices = await api.getDevices();
  assert.deepEqual(devices, []);
});

test("approveReview() posts approved + notes", async () => {
  const api = loadApiWithFetch(async (path, options) => {
    assert.equal(path, "/review/s1/approve");
    assert.equal(options.method, "POST");
    const body = JSON.parse(options.body);
    assert.equal(body.approved, true);
    assert.equal(body.notes, "looks fine");
    return jsonResponse({ session_id: "s1", approved: true });
  });

  const result = await api.approveReview("s1", true, "looks fine");
  assert.equal(result.approved, true);
});

test("a non-ok response with no error field raises a generic message", async () => {
  const api = loadApiWithFetch(async () => jsonResponse({}, { ok: false, status: 500 }));

  await assert.rejects(() => api.getStats(), /failed with status 500/);
});
