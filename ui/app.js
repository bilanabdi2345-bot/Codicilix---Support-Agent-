// Second Brain UI. Talks only to this app on 127.0.0.1 (the page's security
// policy forbids anything else). Nothing is kept in browser storage: when you
// refresh or close the tab, what you saw is gone.
"use strict";

const $ = (s) => document.querySelector(s);

// Tiny DOM builder. Note text is always set as text, never as HTML.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, body) {
  // As a shareable web page, the same answers are worked out inside this browser instead.
  if (window.SB_BACKEND) return window.SB_BACKEND(path, body);
  const opts = { headers: { "X-Second-Brain": "1" } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || res.statusText);
  return json;
}

let STATE = null;
let currentMeeting = null;

// ---------------------------------------------------------------- sidebar
async function refreshState() {
  const { data } = await api("/api/state");
  STATE = data;
  if (STATE.demo) {
    $("#brandSub").textContent = "Demo with simulated notes. It runs entirely in your browser.";
    $("#scopeHint").textContent = "These simulated notes come with this page. Switch a file off and I won't read it.";
    $("#endSession").textContent = "Reset demo";
    $("#endSession").title = "Switch every file back on and clear the conversation";
  }
  renderScope();
  refreshTrust();
  return data;
}

function renderScope() {
  const roots = $("#roots");
  roots.replaceChildren();
  for (const r of STATE.roots) {
    // The bundled simulated notes are shown by name only, never by where they sit on disk.
    roots.append(h("div", { class: "root" },
      h("div", { class: "root-head" },
        h("span", { class: "root-name", title: r.sample ? "Simulated notes" : r.path }, "📁 " + r.name),
        h("span", { class: "file-why" }, `${r.files} files`),
        r.demo ? null : h("button", { class: "root-x", title: "Stop letting the assistant see this folder", onclick: async () => {
          await api("/api/scope/remove", { path: r.path });
          await afterScopeChange();
        } }, "✕")),
      h("div", { class: "root-path" }, r.sample
        ? "Fictional notes for a fictional manager, bundled with the app. Not anyone's real notes." : r.path),
      r.cloud && !r.sample ? h("div", { class: "cloud" },
        `Heads up: this folder is inside ${r.cloud}. ${r.cloud} (not this assistant) already copies files here to the cloud. ` +
        "For real notes, use a folder that isn't synced.") : null));
  }
  $("#useSample").classList.toggle("hidden", !!STATE.demo || STATE.roots.some((r) => r.sample));
  $("#addForm").classList.toggle("hidden", !!STATE.demo);

  const files = $("#files");
  files.replaceChildren();
  if (!STATE.files.length) return;
  const groups = {};
  for (const f of STATE.files) (groups[f.kind_label] = groups[f.kind_label] || []).push(f);
  const order = ["Note", "Reminders", "Draft", "Calendar", "Saved links", "Saved link", "Screenshot", "Other"];
  for (const label of order) {
    if (!groups[label]) continue;
    files.append(h("div", { class: "group-title" }, label === "Note" ? "Notes" : label + (label.endsWith("s") ? "" : "s")));
    for (const f of groups[label]) {
      const input = h("input", { type: "checkbox", checked: f.allowed, disabled: !f.readable,
        "aria-label": `Let the assistant read ${f.display}`,
        onchange: async (e) => {
          await api("/api/scope/toggle", { path: f.path, allowed: e.target.checked });
          await afterScopeChange();
        } });
      files.append(h("div", { class: "file" + (f.switched_off ? " off" : "") + (f.readable ? "" : " unreadable"),
        title: f.readable ? (f.allowed ? "The assistant may read this" : "Switched off: the assistant won't open it") : f.why_not },
        h("label", { class: "switch" }, input, h("span")),
        h("span", { class: "file-name" }, f.display.split("/").pop()),
        f.readable ? null : h("span", { class: "file-why" }, "can't read")));
    }
  }
}

async function afterScopeChange() {
  await refreshState();
  await loadMeetings();
  if (currentMeeting && STATE.roots.length) await loadBrief(currentMeeting);
  else $("#brief").replaceChildren();
}

$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const path = $("#addPath").value.trim();
  if (!path) return;
  const { data } = await api("/api/scope/add", { path });
  if (data.error) {
    $("#addError").textContent = data.error;
    $("#addError").classList.remove("hidden");
    return;
  }
  $("#addError").classList.add("hidden");
  $("#addPath").value = "";
  await afterScopeChange();
});
$("#useSample").addEventListener("click", async () => {
  await api("/api/scope/add", { path: STATE.sample_path });
  await afterScopeChange();
});
$("#endSession").addEventListener("click", async () => {
  if (!STATE.demo && !confirm("Forget everything? This clears the folders you allowed and the proof ledger from memory. Your files are not touched.")) return;
  await api("/api/forget", {});
  currentMeeting = null;
  $("#brief").replaceChildren();
  chatIntro();                       // the conversation is forgotten too
  await refreshState();
  await loadMeetings();
  if (!$("#tab-proof").classList.contains("hidden")) loadProof();
});

// ---------------------------------------------------------------- tabs
for (const t of document.querySelectorAll(".tab")) {
  t.addEventListener("click", () => showTab(t.dataset.tab));
}
function showTab(name) {
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t.dataset.tab === name);
  for (const p of document.querySelectorAll(".panel")) p.classList.toggle("hidden", p.id !== "tab-" + name);
  if (name === "proof") loadProof();
  if (name === "ask") $("#chatInput").focus();
}
$("#trustPill").addEventListener("click", () => showTab("proof"));

// ---------------------------------------------------------------- shared rendering
function srcChip(s) {
  if (!s) return null;
  const name = s.file.split("/").pop();
  return h("button", { class: "src", title: `Open ${s.file} at line ${s.line}`, onclick: () => openSource(s.path, s.line, s.file) },
    "📄 ", name, ` · line ${s.line} · `, h("span", { class: s.date_guessed ? "guess" : "" }, s.date_label + (s.date_guessed ? "?" : "")));
}

function flagEl(f) {
  let cls = "flag";
  if (f.startsWith("overdue")) cls += " overdue";
  else if (f.startsWith("written down")) cls += " repeat";
  else if (f === "changed") { cls += " changed"; f = "changed"; }
  else if (f === "tentative" || f === "not final") { cls += " tentative"; f = "not final"; }
  else if (f.startsWith("due")) cls += " due";
  return h("span", { class: cls }, f);
}

function whyToggle(text) {
  if (!text) return [null, null];
  const box = h("div", { class: "why hidden" }, text);
  const btn = h("button", { class: "why-btn", onclick: () => box.classList.toggle("hidden") }, "Why this?");
  return [btn, box];
}

function itemEl(it) {
  const [whyBtn, whyBox] = whyToggle(it.why);
  const flags = (it.flags || []).filter((f) => !(it.before && (f === "changed" || f === "tentative")));
  const more = (it.more_sources || []);
  const moreRow = more.length ? h("div", { class: "src-row" },
    h("span", { class: "more-src" }, `Also in ${more.length} other note${more.length > 1 ? "s" : ""}:`),
    more.slice(0, 5).map(srcChip)) : null;
  if (it.gaps) {   // an unfinished draft
    return h("div", { class: "item" },
      h("div", { class: "item-head" }, h("span", { class: "headline" }, it.headline), flags.map(flagEl)),
      h("div", {}, it.text),
      h("div", { class: "src-row" }, srcChip(it.source), whyBtn), whyBox,
      it.gaps.map((g) => h("div", { class: "gap" },
        h("span", { class: "gap-line" }, `line ${g.line_no}: ${g.line}`),
        h("div", { class: "gap-fill" }, h("div", { class: "label" }, "Your notes say:"),
          h("span", { class: "quote" }, g.suggestion.text),
          h("div", { class: "src-row" }, srcChip(g.suggestion.source))))));
  }
  return h("div", { class: "item" },
    (it.headline || flags.length) ? h("div", { class: "item-head" },
      it.headline ? h("span", { class: "headline" }, it.headline) : null, flags.map(flagEl)) : null,
    it.before ? h("div", { class: "before" }, h("span", { class: "quote" }, it.before.text), " ", srcChip(it.before.source)) : null,
    it.before ? h("div", { class: "arrow" }, "now ↓") : null,
    h("div", { class: "quote" }, it.text),
    h("div", { class: "src-row" }, srcChip(it.source), whyBtn),
    whyBox, moreRow);
}

function receiptEl(r, what) {
  if (!r) return null;
  const outside = r.outside_scope.length;
  const demo = STATE && STATE.demo;
  return h("div", { class: "receipt" },
    h("div", {},
      `🔒 ${what} read `, h("b", {}, `${r.files_read_count} ${demo ? "simulated " : ""}file${r.files_read_count === 1 ? "" : "s"}`),
      outside ? ` and ${outside} outside your folders (!)` : demo ? "" : ", all inside the folders you allowed",
      ". Wrote ", h("b", {}, "0 files"), ". Sent ", h("b", {}, "nothing"), demo ? " out of your browser. Kept " : " off this device. Kept ",
      h("b", {}, "nothing"), ": it was built in memory and thrown away. Refresh and it's gone from this page too."),
    r.files_read_count ? h("details", {}, h("summary", {}, demo ? "Which files, exactly" : "Which files, exactly (as recorded by the privacy guard)"),
      h("ul", {}, r.files_read.map((f) => h("li", {}, f)))) : null,
    r.blocked.length ? h("div", { class: "error" }, "Blocked during this answer: " + r.blocked.join("; ")) : null);
}

// ---------------------------------------------------------------- meetings
async function loadMeetings() {
  const box = $("#meetings");
  if (!STATE.roots.length) {
    box.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "Nothing to look at yet"),
      "Add a folder of notes on the left, or try the sample manager notes. I'll read them only when you ask, and keep nothing."));
    return;
  }
  const { data } = await api("/api/meetings");
  if (!data.meetings.length) {
    box.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No meetings found"),
      data.has_calendar ? "Your calendar files have no events." : "Add a calendar file (.ics) to the folder to pick a meeting to prepare for."));
    return;
  }
  box.replaceChildren(h("div", { class: "meetings" }, data.meetings.map((m) =>
    h("button", { class: "meeting" + (m.upcoming ? "" : " past") + (m.id === currentMeeting ? " active" : ""),
      onclick: () => loadBrief(m.id) },
      h("div", { class: "meeting-when" }, (m.upcoming ? "" : "Past · ") + m.date_label),
      h("div", { class: "meeting-title" }, m.title),
      h("div", { class: "meeting-who" }, m.attendees.join(", "))))));
}

async function loadBrief(id) {
  currentMeeting = id;
  for (const b of document.querySelectorAll(".meeting")) b.classList.remove("active");
  await loadMeetings();
  const out = $("#brief");
  out.replaceChildren(h("div", { class: "spinner" }, "Reading your notes…"));
  const { data, receipt, ms } = await api("/api/brief", { id });
  if (data.error) return out.replaceChildren(h("div", { class: "error" }, data.error));
  out.replaceChildren(...renderBrief(data, { ms }), receiptEl(receipt, "This brief"));
  refreshTrust();
}

// Shared by the meeting tab and the chat. In the chat (compact), sections fold up.
function renderBrief(data, opts = {}) {
  const m = data.meeting;
  const parts = [
    h("div", { class: "brief-head" + (opts.compact ? " compact" : "") },
      h(opts.compact ? "h2" : "h1", {}, m.title),
      h("div", { class: "brief-meta" }, m.date_label,
        opts.ms !== undefined ? ` · prepared from ${data.stats.lines_considered} lines of your notes in ${opts.ms} ms` : ""),
      m.attendees.length ? h("div", { class: "people" }, m.attendees.map((a) => h("span", { class: "person" }, a))) : null,
      m.agenda.length ? h("div", { class: "agenda" }, "Agenda: " + m.agenda.join(" · ")) : null),
  ];
  if (data.talking_points.length) {
    parts.push(h("div", { class: "card points" },
      h("h2", {}, "If you only read one thing"),
      h("div", { class: "sub" }, "Talking points drawn from what your notes say, and what they leave open"),
      h("ol", {}, data.talking_points.map((p) => h("li", {}, p.text,
        h("div", { class: "src-row" }, srcChip(p.source), h("span", { class: "more-src" }, p.why)))))));
  }
  for (const s of data.sections) {
    const body = s.plain
      ? h("ul", { class: "plain-list" }, s.items.map((g) => h("li", {}, g.text, g.source ? [" ", srcChip(g.source)] : null)))
      : s.items.map(itemEl);
    const more = s.more ? h("div", { class: "more-src" }, `…and ${s.more} more`) : null;
    if (opts.compact) {
      const open = ["changed", "actions"].includes(s.id);
      parts.push(h("details", { class: "card fold", open },
        h("summary", {}, h("span", { class: "fold-title" }, s.title),
          h("span", { class: "fold-count" }, s.plain ? "" : ` ${s.items.length}`)),
        s.subtitle ? h("div", { class: "sub" }, s.subtitle) : null, body, more));
    } else {
      parts.push(h("div", { class: "card", id: "sec-" + s.id },
        h("h2", {}, s.title), s.subtitle ? h("div", { class: "sub" }, s.subtitle) : null, body, more));
    }
  }
  return parts;
}

// ---------------------------------------------------------------- chat
// The conversation lives only in this page's memory: no storage, no server-side history.
const chatLog = $("#chatLog");
const CHAT_START = ["Prepare me for my next meeting", "What do I owe people?", "What has changed?",
  "Catch me up on data residency", "Tell me about Dana", "When is the launch?", "What's Tom's phone number?"];

function chipsEl(list) {
  return h("div", { class: "chips" }, list.map((q) => h("button", { class: "chip", onclick: () => sendChat(q) }, q)));
}
function userMsg(text) {
  return h("div", { class: "msg user" }, h("div", { class: "bubble" }, text));
}
function botMsg(children) {
  return h("div", { class: "msg bot" },
    h("div", { class: "avatar", "aria-hidden": "true" }, h("span"), h("span"), h("span")),
    h("div", { class: "bot-body" }, children));
}
function chatIntro() {
  chatLog.replaceChildren(botMsg([
    h("p", { class: "bot-text" }, "Hi, I'm your Second Brain. Ask me anything about the notes you've allowed: "
      + "prepare for a meeting, catch up on a person or topic, or find something you wrote down weeks ago."),
    h("p", { class: "bot-note" }, "I only read your files when you ask, I quote them rather than guess, and nothing "
      + "leaves this device."),
    chipsEl(CHAT_START)]));
}
function miniReceipt(r) {
  if (!r || !r.files_read_count) return null;
  const what = STATE && STATE.demo ? "simulated file" : "file";
  return h("details", { class: "mini-receipt" },
    h("summary", {}, `🔒 Read ${r.files_read_count} ${what}${r.files_read_count === 1 ? "" : "s"}`
      + `${r.outside_scope.length ? ` (+${r.outside_scope.length} outside your folders!)` : STATE && STATE.demo ? "" : ", all inside your folders"}`
      + " · wrote 0 · sent nothing · kept nothing"),
    h("ul", {}, r.files_read.map((f) => h("li", {}, f))));
}
function renderReply(d, receipt) {
  const parts = [];
  if (d.kind === "brief") {
    parts.push(h("p", { class: "bot-text" }, d.text), ...renderBrief(d.brief, { compact: true }));
  } else if (d.kind === "answer") {
    parts.push(h("p", { class: "summary " + d.status }, d.summary));
    if (d.confidence) parts.push(h("div", { class: "conf" }, d.confidence === "high"
      ? "Confidence: high. These lines match your question directly."
      : "Confidence: medium. These lines match part of your question, so check the sources."));
    if (d.items.length) parts.push(h("div", { class: "card answer-card" }, d.items.map(itemEl)));
    if ((d.gaps || []).length) parts.push(h("ul", { class: "plain-list" }, d.gaps.map((g) => h("li", {}, g.text))));
  } else {
    parts.push(h("p", { class: "bot-text" }, d.text));
    if (d.lines) parts.push(h("ul", { class: "help-list" }, d.lines.map((l) => h("li", {}, l))));
  }
  if (d.suggestions && d.suggestions.length) parts.push(chipsEl(d.suggestions));
  parts.push(miniReceipt(receipt));
  return parts;
}

let chatBusy = false;
async function sendChat(text) {
  text = (text || "").trim();
  if (!text || chatBusy) return;
  showTab("ask");
  $("#chatInput").value = "";
  chatLog.append(userMsg(text));
  const pending = botMsg([h("div", { class: "spinner" }, "Reading your notes…")]);
  chatLog.append(pending);
  pending.scrollIntoView({ block: "nearest" });
  if (!STATE.roots.length) {
    pending.replaceWith(botMsg([h("p", { class: "bot-text" }, "I can't see any notes yet. Add a folder on the left "
      + "(or use the sample notes) and ask again. Until then I have nothing to go on, and I won't guess.")]));
    return;
  }
  chatBusy = true;
  try {
    const { data, receipt } = await api("/api/chat", { message: text });
    const reply = botMsg(renderReply(data, receipt));
    pending.replaceWith(reply);
    reply.scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (e) {
    pending.replaceWith(botMsg([h("div", { class: "error" }, "Something went wrong: " + e.message)]));
  } finally {
    chatBusy = false;
    refreshTrust();
    $("#chatInput").focus();
  }
}
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chatInput").value); });
$("#newChat").addEventListener("click", () => { chatIntro(); $("#chatInput").focus(); });
chatIntro();

// ---------------------------------------------------------------- source drawer
async function openSource(path, line, file) {
  const { data } = await api(`/api/source?path=${encodeURIComponent(path)}&line=${line}`);
  $("#drawerTitle").textContent = data.error ? file : `${data.file} · line ${data.line}`;
  const body = $("#drawerBody");
  if (data.error) body.replaceChildren(h("div", { class: "error" }, data.error));
  else body.replaceChildren(...data.lines.map((l) =>
    h("span", { class: "ln" + (l.n === data.line ? " hit" : "") }, h("span", { class: "ln-n" }, l.n), l.text || " ")));
  $("#drawerPath").textContent = data.path_display || data.path || "";
  $("#drawer").classList.remove("hidden");
  $("#scrim").classList.remove("hidden");
  const hit = body.querySelector(".hit");
  if (hit) hit.scrollIntoView({ block: "center" });
  refreshTrust();
}
function closeDrawer() { $("#drawer").classList.add("hidden"); $("#scrim").classList.add("hidden"); }
$("#drawerClose").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

// ---------------------------------------------------------------- proof
async function refreshTrust() {
  try {
    const { data } = await api("/api/ledger");
    const pill = $("#trustPill");
    if (data.demo) {
      pill.classList.toggle("alert", data.network_requests > 0);
      $("#trustText").textContent = data.network_requests
        ? `Check the proof: ${data.network_requests} network request(s)`
        : `In your browser · 0 sent · ${data.files_read} simulated file${data.files_read === 1 ? "" : "s"} read`;
      return data;
    }
    const leaks = data.reads_outside_scope + data.reads_switched_off;
    const realBlocks = data.writes_blocked + data.net_blocked + data.exec_blocked;
    pill.classList.toggle("alert", leaks > 0 || realBlocks > 0);
    $("#trustText").textContent = leaks || realBlocks
      ? `Check the proof: ${realBlocks} blocked, ${leaks} unexpected reads`
      : `On this device · 0 sent · 0 written · ${data.files_read} file${data.files_read === 1 ? "" : "s"} read`;
    return data;
  } catch (e) { return null; }
}

let lastLeakTest = null;
function leakResultsEl() {
  if (!lastLeakTest) return [];
  return lastLeakTest.map((r) => h("div", { class: "test-row" },
    h("span", { class: "badge " + (r.blocked ? "ok" : "bad") }, r.blocked ? "Blocked" : "NOT blocked"),
    h("div", {}, h("div", {}, r.attempt), h("div", { class: "test-how" }, r.how))));
}

function loadDemoProof(box, d) {
  const stat = (n, label, sub, good) => h("div", { class: "stat" },
    h("div", { class: "n " + (good ? "good" : "bad") }, n), h("div", { class: "l" }, label), sub ? h("div", { class: "s" }, sub) : null);
  const testBox = h("div", {}, leakResultsEl());
  box.replaceChildren(
    h("div", { class: "card" },
      h("h2", {}, "Where this demo runs"),
      h("div", { class: "sub" }, "Everything on this page is worked out inside your browser, from simulated notes bundled with "
        + "the page. No server does the thinking, and nothing you type is sent anywhere."),
      h("div", { class: "stats" },
        stat(d.files_read, "simulated files read", "bundled with this page, not anyone's real notes", true),
        stat(d.network_requests, "network requests since the page loaded",
          d.network_requests ? d.network_list.join(", ") : "counted by your browser's own performance log", d.network_requests === 0),
        stat(0, "of your own files read", "this demo can't see the files on your computer", true),
        stat(0, "things saved in your browser", "no cookies or storage: refresh and the conversation is gone", true))),
    h("div", { class: "card" },
      h("h2", {}, "Try to make it leak"),
      h("div", { class: "sub" }, "This makes the page itself try to send data to another website. Your browser should refuse every attempt before anything is sent."),
      h("button", { class: "primary", onclick: async () => {
        testBox.replaceChildren(h("div", { class: "spinner" }, "Trying…"));
        const { data } = await api("/api/leaktest", {});
        lastLeakTest = data.results;
        await loadProof();
      } }, "Run the leak test"),
      testBox),
    h("div", { class: "card" },
      h("h2", {}, "Don't trust me, check it yourself"),
      h("ul", { class: "help-list" },
        h("li", {}, "Open your browser's developer tools (F12), go to the Network tab and use the chat: no requests appear."),
        h("li", {}, "Or turn on flight mode once the page has loaded: the chat keeps working, because it never needed the internet."))),
    h("div", { class: "card" },
      h("h2", {}, "The full app on your own computer"),
      h("div", { class: "sub" }, "This page is a demo with made-up notes. The full app runs on your own computer, reads only the "
        + "folders you allow, and adds a privacy guard inside the program that blocks every network connection, file write and "
        + "program launch. It needs only Python: run python app.py in the second-brain folder.")),
  );
}

async function loadProof() {
  const box = $("#proof");
  const d = await refreshTrust();
  if (!d) return;
  if (d.demo) return loadDemoProof(box, d);
  const stat = (n, label, sub, good) => h("div", { class: "stat" },
    h("div", { class: "n " + (good ? "good" : "bad") }, n), h("div", { class: "l" }, label), sub ? h("div", { class: "s" }, sub) : null);
  const testBox = h("div", {}, leakResultsEl());
  const kindLabel = {
    write_blocked: ["Blocked", "blocked"], net_blocked: ["Blocked", "blocked"], exec_blocked: ["Blocked", "blocked"],
    net_loopback: ["Local", "ok"], exec_allowed: ["Allowed", "ok"], read_outside: ["Unexpected read", "blocked"],
    read_switched_off: ["Read a switched-off file", "blocked"], forget: ["Forgot", "ok"],
  };
  box.replaceChildren(
    h("div", { class: "card" },
      h("h2", {}, "The one rule, checked live"),
      h("div", { class: "sub" }, "These numbers come from the privacy guard inside this app (Python audit hooks), not from a promise. " +
        "Once the guard is on, nothing in this app can switch it off. It runs before any file write, network connection, address lookup or program launch, and refuses the ones that break the rule."),
      h("div", { class: "stats" },
        stat(d.files_read, "of your files read", "only inside folders you allowed, only when you asked", true),
        stat(d.reads_outside_scope + d.reads_switched_off, "reads outside what you allowed", "files outside your folders, or ones you switched off", d.reads_outside_scope + d.reads_switched_off === 0),
        stat(0, "files written", d.writes_blocked ? `${d.writes_blocked} attempt(s) blocked` : "the app can't create, change or delete files", true),
        stat(0, "connections off this device", d.net_blocked ? `${d.net_blocked} attempt(s) blocked` : "not even a DNS lookup", true),
        stat(0, "other programs started", d.exec_blocked ? `${d.exec_blocked} attempt(s) blocked` : "apart from opening your browser once", true),
        stat(d.test_blocks, "blocked in leak tests you ran", "see below", true))),
    h("div", { class: "card" },
      h("h2", {}, "Try to make it leak"),
      h("div", { class: "sub" }, "This makes the app itself try to send data out, write a copy and start another program. Each attempt should be refused before anything happens."),
      h("button", { class: "primary", onclick: async () => {
        testBox.replaceChildren(h("div", { class: "spinner" }, "Trying…"));
        const { data } = await api("/api/leaktest", {});
        lastLeakTest = data.results;
        await loadProof();
      } }, "Run the leak test"),
      testBox),
    h("div", { class: "card" },
      h("h2", {}, "Don't trust me, check it yourself"),
      h("div", { class: "sub" }, "Use your computer's own tools to watch this app (process id " + d.pid + ")."),
      h("div", {}, "Windows PowerShell: list every network connection this app has. Only 127.0.0.1 should appear:"),
      h("div", { class: "cmd" }, `Get-NetTCPConnection -OwningProcess ${d.pid} | Select-Object LocalAddress,LocalPort,RemoteAddress,State`),
      h("div", {}, "Or open Resource Monitor → Network and tick python.exe. On a Mac: "),
      h("div", { class: "cmd" }, `lsof -i -a -p ${d.pid}`),
      h("div", {}, "Pull the network cable or turn on flight mode: everything still works, because nothing here needs the internet."),
      h("div", { class: "sub" }, "The guard is in guard.py (about 300 lines), and the whole app is plain Python with no third-party code.")),
    h("div", { class: "card" },
      h("h2", {}, "What the guard saw"),
      h("div", { class: "sub" }, "File reads are logged by path only, never content. Kept in memory and cleared when you end the session."),
      d.events.length ? h("table", { class: "events" }, h("tbody", {}, d.events.slice().reverse().slice(0, 60).map((e) => {
        const [label, cls] = kindLabel[e.kind] || [e.kind, ""];
        return h("tr", {}, h("td", {}, new Date(e.t * 1000).toLocaleTimeString()),
          h("td", {}, h("span", { class: "ev-kind " + cls }, label + (e.test ? " (leak test)" : ""))), h("td", {}, e.detail));
      }))) : h("div", { class: "more-src" }, "Nothing unusual yet. Ordinary reads of your allowed files are counted above, not listed here.")),
  );
}

// ---------------------------------------------------------------- start
(async function start() {
  await refreshState();
  await loadMeetings();
  setInterval(refreshTrust, 5000);
})();
