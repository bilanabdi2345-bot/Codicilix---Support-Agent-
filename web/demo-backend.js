/*
 * demo-backend.js - stands in for app.py when Second Brain runs as a shareable web page.
 *
 * The notes are simulated (a fictional manager's notes, bundled with this page as
 * SB_DEMO_FILES). Every answer is worked out by engine.js inside the visitor's
 * browser. Nothing is sent anywhere and nothing is stored.
 */
"use strict";
(() => {
  const E = window.SBEngine;
  const TODAY_ISO = window.SB_DEMO_TODAY || "2026-11-22";
  const TODAY = E.fromIso(TODAY_ISO);
  E.setYear(+TODAY_ISO.slice(0, 4));
  const ROOT = "Simulated notes";
  const FILES = window.SB_DEMO_FILES.map((f) => ({ ...f, path: `demo/${f.display}`, root: ROOT }));
  const off = new Set();
  const readCounts = new Map();
  const loadedAt = performance.now();

  const inventory = () => E.inventory(FILES, off);
  const context = (inv) => ({ switched_off: inv.filter((f) => f.switched_off).map((f) => f.display),
    unreadable: inv.filter((f) => !f.readable).map((f) => f.display) });
  const publicFile = ({ text, ...rest }) => rest;   // the sidebar gets names and sizes, never contents

  function readAllRecorded(inv) {
    const docs = E.readAll(inv);
    const read = inv.filter((f) => f.allowed).map((f) => f.display);
    for (const d of read) readCounts.set(d, (readCounts.get(d) || 0) + 1);
    return { docs, read };
  }
  const receipt = (read) => ({ files_read: [...new Set(read)].sort(), files_read_count: new Set(read).size,
    outside_scope: [], blocked: [], network: [], written: 0 });

  // Network requests this page itself has made since it loaded (should be none). The
  // leak test's own attempts are left out: they are reported separately, as blocked.
  const LEAK_TEST_MARK = "second-brain-leak-test";
  function networkSinceLoad() {
    try {
      return performance.getEntriesByType("resource")
        .filter((e) => e.startTime >= loadedAt && /^https?:/i.test(e.name) && !e.name.includes(LEAK_TEST_MARK))
        .map((e) => e.name);
    } catch (e) { return []; }
  }

  const routes = {
    "GET /api/state": () => {
      const inv = inventory();
      return { roots: [{ path: "demo", name: ROOT, cloud: null, files: inv.length, sample: true, demo: true }],
        files: inv.map(publicFile), today: TODAY_ISO, sample_path: "demo", guard: true, pid: null, demo: true };
    },
    "POST /api/scope/toggle": (b) => {
      const key = String(b.path || "").toLowerCase();
      if (b.allowed) off.delete(key); else off.add(key);
      return { ok: true };
    },
    "POST /api/scope/add": () => ({ error: "This online demo only uses its simulated notes. To use your own folders, run the app on your own computer." }),
    "POST /api/scope/remove": () => ({ ok: true }),
    "GET /api/meetings": (b, rec) => {
      const inv = inventory();
      const cal = inv.filter((f) => f.kind === "calendar");
      const { docs, read } = readAllRecorded(cal);
      rec.push(...read);
      return { meetings: E.listMeetings(docs, TODAY), has_calendar: cal.some((f) => f.allowed) };
    },
    "POST /api/brief": (b, rec) => {
      const inv = inventory(); const { docs, read } = readAllRecorded(inv); rec.push(...read);
      return E.meetingBrief(docs, String(b.id || ""), TODAY, context(inv));
    },
    "POST /api/ask": (b, rec) => {
      const inv = inventory(); const { docs, read } = readAllRecorded(inv); rec.push(...read);
      return E.ask(docs, String(b.q || "").slice(0, 500), TODAY, context(inv));
    },
    "POST /api/chat": (b, rec) => {
      const inv = inventory(); const { docs, read } = readAllRecorded(inv); rec.push(...read);
      return E.chat(docs, String(b.message || "").slice(0, 500), TODAY, context(inv));
    },
    "GET /api/source": (b, rec) => {
      const f = inventory().find((x) => x.key === String(b.path || "").toLowerCase());
      if (!f) return { error: "That file isn't part of the simulated notes." };
      if (!f.allowed) return { error: "You've switched that file off, so I won't open it." };
      rec.push(f.display);
      const lines = f.text.split(/\r\n|\r|\n/);
      if (lines.length && lines[lines.length - 1] === "") lines.pop();
      const n = Math.max(1, parseInt(b.line, 10) || 1);
      const lo = Math.max(1, n - 8), hi = Math.min(lines.length, n + 8);
      const out = [];
      for (let i = lo; i <= hi; i++) out.push({ n: i, text: lines[i - 1] });
      return { file: f.display, path: f.path, path_display: `${ROOT}/${f.display}`, line: n, total: lines.length, lines: out };
    },
    "GET /api/ledger": () => {
      const net = networkSinceLoad();
      return { demo: true, files_read: readCounts.size, reads_total: [...readCounts.values()].reduce((a, b) => a + b, 0),
        reads_outside_scope: 0, reads_switched_off: 0, writes_blocked: 0, net_blocked: 0, exec_blocked: 0,
        net_loopback: 0, test_blocks: 0, network_requests: net.length, network_list: net.slice(-10), events: [], pid: null };
    },
    "POST /api/leaktest": async () => ({ results: await browserLeakTest() }),
    "POST /api/forget": () => { off.clear(); readCounts.clear(); return { ok: true }; },
  };

  // Try to send data out of this page. The page's security policy should make the
  // browser refuse every attempt before anything is sent.
  async function browserLeakTest() {
    const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timed out")), ms))]);
    const attempts = [
      ["Send a web request to https://example.com", () => withTimeout(fetch("https://example.com/?second-brain-leak-test=1", { mode: "no-cors" }), 4000)],
      ["Load an image from another website (a classic way to leak data)", () => withTimeout(new Promise((res, rej) => {
        const img = new Image(); img.onload = () => res("loaded"); img.onerror = () => rej(new Error("refused"));
        img.src = "https://example.com/pixel.png?second-brain-leak-test=1"; }), 4000)],
      ["Open a live connection (WebSocket) to another server", () => withTimeout(new Promise((res, rej) => {
        let ws; try { ws = new WebSocket("wss://example.com/socket?second-brain-leak-test=1"); } catch (e) { rej(e); return; }
        ws.onopen = () => { ws.close(); res("opened"); }; ws.onerror = () => rej(new Error("refused")); }), 4000)],
    ];
    const out = [];
    for (const [name, fn] of attempts) {
      try {
        await fn();
        out.push({ attempt: name, blocked: false, how: "NOT blocked: this browser let it through" });
      } catch (e) {
        out.push({ attempt: name, blocked: true, how: "refused by your browser before anything was sent (this page's security policy)" });
      }
    }
    return out;
  }

  window.SB_BACKEND = async (pathAndQuery, body) => {
    const [path, qs] = pathAndQuery.split("?");
    const method = body === undefined ? "GET" : "POST";
    const params = Object.fromEntries(new URLSearchParams(qs || ""));
    const fn = routes[`${method} ${path}`];
    if (!fn) throw new Error("not found");
    const started = performance.now();
    const rec = [];
    const data = await fn({ ...params, ...(body || {}) }, rec);
    return { data, receipt: receipt(rec), ms: Math.round(performance.now() - started) };
  };
})();
