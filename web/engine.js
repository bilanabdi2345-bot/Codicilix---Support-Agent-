/*
 * engine.js - Second Brain's analysis engine for the browser.
 *
 * A faithful port of sources.py + brain.py so the shareable demo can run entirely
 * inside the visitor's browser: same rules, same thresholds, same results. Nothing
 * is cached and nothing is sent anywhere; every call works on the notes it is given.
 */
"use strict";
const SBEngine = (() => {
  // ------------------------------------------------------------------ small helpers
  const DAY = 86400000;
  const setOf = (xs) => new Set(xs);
  const inter = (a, b) => { const o = new Set(); for (const x of a) if (b.has(x)) o.add(x); return o; };
  const minus = (a, b) => { const o = new Set(); for (const x of a) if (!b.has(x)) o.add(x); return o; };
  const unionAll = (sets) => { const o = new Set(); for (const s of sets) for (const x of s) o.add(x); return o; };
  const any = (xs, fn) => { for (const x of xs) if (fn(x)) return true; return false; };
  const all = (xs, fn) => { for (const x of xs) if (!fn(x)) return false; return true; };
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);
  const isDigits = (w) => /^\d+$/.test(w);
  const isAlpha = (w) => /^[a-z]+$/i.test(w);
  const cap1 = (s) => s.slice(0, 1).toUpperCase() + s.slice(1);
  const capitalize = (s) => s.slice(0, 1).toUpperCase() + s.slice(1).toLowerCase();
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const strip = (s, chars) => {
    let a = 0, b = s.length;
    while (a < b && chars.includes(s[a])) a++;
    while (b > a && chars.includes(s[b - 1])) b--;
    return s.slice(a, b);
  };
  const lstrip = (s, chars) => { let a = 0; while (a < s.length && chars.includes(s[a])) a++; return s.slice(a); };
  const g = (rx) => new RegExp(rx.source, rx.flags.includes("g") ? rx.flags : rx.flags + "g");
  // max() like Python: first element with the largest key (keys are arrays compared left to right)
  const cmpKey = (a, b) => {
    for (let i = 0; i < a.length; i++) {
      const x = a[i], y = b[i];
      if (x === y) continue;
      if (typeof x === "boolean" || typeof y === "boolean") return (x ? 1 : 0) - (y ? 1 : 0);
      return x < y ? -1 : 1;
    }
    return 0;
  };
  const maxBy = (xs, keyFn) => {
    let best = null, bk = null;
    for (const x of xs) { const k = keyFn(x); if (best === null || cmpKey(k, bk) > 0) { best = x; bk = k; } }
    return best;
  };
  const sortBy = (xs, keyFn) => xs.slice().sort((a, b) => cmpKey(keyFn(a), keyFn(b)));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  // ------------------------------------------------------------------ dates (day numbers)
  function dnum(y, m, d) {
    if (!(m >= 1 && m <= 12 && d >= 1 && d <= 31)) return null;
    const dt = new Date(Date.UTC(2000, m - 1, d));
    dt.setUTCFullYear(y);
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
    return Math.round(dt.getTime() / DAY);
  }
  const ymd = (n) => { const d = new Date(n * DAY); return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()]; };
  const weekday = (n) => (new Date(n * DAY).getUTCDay() + 6) % 7;   // Monday = 0, as in Python
  const mod = (a, b) => ((a % b) + b) % b;
  const pad = (x) => String(x).padStart(2, "0");
  const isoDate = (n) => { const [y, m, d] = ymd(n); return `${y}-${pad(m)}-${pad(d)}`; };
  const fromIso = (s) => { const [y, m, d] = s.split("-").map(Number); return dnum(y, m, d); };
  const MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  let CURRENT_YEAR = new Date().getUTCFullYear();
  const fmtDate = (n) => {
    if (n === null || n === undefined) return "undated";
    const [y, m, d] = ymd(n);
    return `${d} ${MON_ABBR[m - 1]}` + (y === CURRENT_YEAR ? "" : ` ${y}`);
  };
  const lastDay = (y, m) => dnum(y + (m === 12 ? 1 : 0), (m % 12) + 1, 1) - 1;

  const MONTHS = { january: 1, jan: 1, february: 2, feb: 2, march: 3, mar: 3, april: 4, apr: 4, may: 5,
    june: 6, jun: 6, july: 7, jul: 7, august: 8, aug: 8, september: 9, sept: 9, sep: 9, october: 10, oct: 10,
    november: 11, nov: 11, december: 12, dec: 12 };
  const WEEKDAYS = { mon: 0, monday: 0, tue: 1, tues: 1, tuesday: 1, wed: 2, wednesday: 2, thu: 3, thur: 3,
    thurs: 3, thursday: 3, fri: 4, friday: 4, sat: 5, saturday: 5, sun: 6, sunday: 6 };
  const byLenDesc = (xs) => xs.slice().sort((a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0));
  const MON = byLenDesc(Object.keys(MONTHS)).join("|");
  const WD = byLenDesc(Object.keys(WEEKDAYS)).join("|");
  const DATE_PATTERNS = [
    ["iso", /\b(20\d\d)-(\d{1,2})-(\d{1,2})\b/g],
    ["ical", /\b(20\d\d)(\d\d)(\d\d)T?\b/g],
    ["dmy", /(?<![\d/])(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?(?![\d/])/g],
    ["d_mon", new RegExp(`\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+(${MON})\\b\\.?(?:,?\\s+(20\\d\\d))?`, "gi")],
    ["mon_d", new RegExp(`\\b(${MON})\\b\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b(?:,?\\s+(20\\d\\d))?`, "gi")],
    ["by_wd", new RegExp(`\\b(?:by|before|on|next)\\s+(${WD})\\b`, "gi")],
    ["eow", /\b(?:eow|end of (?:the )?week)\b/gi],
    ["eom", /\b(?:eom|end of (?:the )?month)\b/gi],
    ["end_mon", new RegExp(`\\bend of (${MON})\\b`, "gi")],
    ["tomorrow", /\btomorrow\b/gi],
  ];

  function inferYear(month, day, ref) {
    const [ry] = ymd(ref);
    let d = dnum(ry, month, day);
    if (d === null) return null;
    if (d - ref < -183) { const [y, m, dd] = ymd(d); d = dnum(y + 1, m, dd); }
    else if (d - ref > 183) { const [y, m, dd] = ymd(d); d = dnum(y - 1, m, dd); }
    return d;
  }

  // All dates in `text` as [start, end, dayNumber, kind].
  function findDates(text, ref) {
    const found = [], taken = [];
    const free = (a, b) => taken.every(([s, e]) => b <= s || a >= e);
    for (const [kind, rx] of DATE_PATTERNS) {
      for (const m of text.matchAll(rx)) {
        const start = m.index, end = m.index + m[0].length;
        if (!free(start, end)) continue;
        let d = null;
        const [ry, rm] = ymd(ref);
        if (kind === "iso" || kind === "ical") d = dnum(+m[1], +m[2], +m[3]);
        else if (kind === "dmy") {
          const day = +m[1], mon = +m[2];
          if (!(mon >= 1 && mon <= 12 && day >= 1 && day <= 31)) continue;
          if (m[3]) d = dnum(+m[3] + (m[3].length === 2 ? 2000 : 0), mon, day);
          else d = inferYear(mon, day, ref);
        } else if (kind === "d_mon") {
          const mon = MONTHS[m[2].toLowerCase()], day = +m[1];
          d = m[3] ? dnum(+m[3], mon, day) : inferYear(mon, day, ref);
        } else if (kind === "mon_d") {
          const mon = MONTHS[m[1].toLowerCase()], day = +m[2];
          d = m[3] ? dnum(+m[3], mon, day) : inferYear(mon, day, ref);
        } else if (kind === "by_wd") {
          const wd = WEEKDAYS[m[1].toLowerCase()];
          d = ref + (mod(wd - weekday(ref), 7) || 7);
        } else if (kind === "eow") d = ref + mod(4 - weekday(ref), 7);
        else if (kind === "eom") d = lastDay(ry, rm);
        else if (kind === "end_mon") {
          const mon = MONTHS[m[1].toLowerCase()];
          d = lastDay(ry + (mon < rm - 6 ? 1 : 0), mon);
        } else if (kind === "tomorrow") d = ref + 1;
        if (d !== null && d !== undefined) { found.push([start, end, d, kind]); taken.push([start, end]); }
      }
    }
    return found.sort((a, b) => cmpKey(a, b));
  }

  // ------------------------------------------------------------------ files and documents
  const TEXT_EXT = [".md", ".markdown", ".txt", ".text", ".org"], CAL_EXT = [".ics"], LINK_EXT = [".url", ".webloc"];
  const IMAGE_EXT = [".png", ".jpg", ".jpeg", ".gif", ".heic", ".bmp", ".webp", ".tif", ".tiff"];
  const KIND_LABEL = { note: "Note", calendar: "Calendar", link: "Saved link", links: "Saved links",
    reminders: "Reminders", draft: "Draft", screenshot: "Screenshot", actions: "Action list" };
  const extOf = (name) => { const i = name.lastIndexOf("."); return i > 0 ? name.slice(i).toLowerCase() : ""; };
  const baseName = (p) => p.split("/").pop();
  const stemName = (p) => { const b = baseName(p); const i = b.lastIndexOf("."); return i > 0 ? b.slice(0, i) : b; };

  function kindOf(display) {
    const name = baseName(display).toLowerCase(), ext = extOf(name);
    const parts = display.toLowerCase().split("/").slice(0, -1);
    if (CAL_EXT.includes(ext)) return "calendar";
    if (ext === ".csv") return "actions";
    if (LINK_EXT.includes(ext)) return "link";
    if (IMAGE_EXT.includes(ext)) return "screenshot";
    if (TEXT_EXT.includes(ext)) {
      if (name.includes("draft") || parts.some((p) => p === "drafts" || p === "draft")) return "draft";
      if (/remind|todo|to-do|tasks/.test(name)) return "reminders";
      if (/links?\b|bookmark/.test(name) || parts.some((p) => p === "links" || p === "bookmarks")) return "links";
      return "note";
    }
    return null;
  }

  // files: [{path, display, root, modified: "YYYY-MM-DD", size, text}] -> inventory entries
  function inventory(files, off) {
    return files.map((f) => {
      const k = kindOf(f.display);
      let readable = true, whyNot = "";
      if (k === null) { readable = false; whyNot = "file type not supported"; }
      else if (k === "screenshot") { readable = false; whyNot = "image - no on-device text recognition yet"; }
      else if (f.size > 2000000) { readable = false; whyNot = "larger than 2 MB"; }
      const key = f.path.toLowerCase();
      return { path: f.path, key, root: f.root, display: f.display, kind: k || "other",
        kind_label: KIND_LABEL[k || ""] || "Other", size: f.size, modified: f.modified, readable,
        why_not: whyNot, allowed: readable && !off.has(key), switched_off: off.has(key), text: f.text };
    });
  }

  const ATTENDEE_RX = /^\s*(?:attendees|with|people|present|who)\s*[:\-]\s*(.+)$/i;
  const splitLines = (text) => { const ls = text.split(/\r\n|\r|\n/); if (ls.length && ls[ls.length - 1] === "") ls.pop(); return ls; };

  function splitNames(s) {
    const names = [];
    for (let p of s.split(/,|&|\band\b|\+|;|\//)) {
      p = strip(p.replace(/\(.*?\)/g, ""), " .-");
      if (p && p.length < 40) names.push(p);
    }
    return names;
  }

  // ---- spreadsheet action lists (.csv), as in sources.csv_rows_to_lines ----
  function parseCsv(text) {
    const rows = []; let row = [], cell = "", q = false, i = 0;
    while (i < text.length) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i += 2; continue; } q = false; i++; continue; }
        cell += c; i++; continue;
      }
      if (c === '"') { q = true; i++; continue; }
      if (c === ",") { row.push(cell); cell = ""; i++; continue; }
      if (c === "\r") { i++; continue; }
      if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; i++; continue; }
      cell += c; i++;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }
  const CSV_COLS = { action: ["action", "task", "todo", "to do", "item", "what", "description"],
    owner: ["owner", "who", "assignee", "assigned to", "person", "lead"],
    due: ["due", "due date", "deadline", "by", "date", "when"],
    status: ["status", "done", "state", "complete", "completed"] };
  const DONE_WORDS = new Set(["done", "complete", "completed", "closed", "finished", "yes", "y", "true", "x", "✅"]);
  function csvRowsToLines(text) {
    const rows = parseCsv(text);
    if (!rows.length) return [[], []];
    const header = rows[0].map((c) => c.trim().toLowerCase());
    const col = {};
    for (const [key, names] of Object.entries(CSV_COLS)) {
      for (let i = 0; i < header.length; i++) {
        if (names.includes(header[i]) && !Object.values(col).includes(i)) { col[key] = i; break; }
      }
    }
    const hasHeader = "action" in col;
    const body = hasHeader ? rows.slice(1) : rows;
    const lines = hasHeader ? ["# " + rows[0].join(", ")] : [], owners = [];
    for (const r of body) {
      const cell = (k) => (k in col && col[k] < r.length ? r[col[k]].trim() : "");
      const action = hasHeader ? cell("action") : r.map((c) => c.trim()).filter(Boolean).join(" ");
      if (!action) { lines.push(""); continue; }
      const owner = cell("owner"), due = cell("due"), status = cell("status").toLowerCase();
      const who = ["", "me", "i", "you", "myself"].includes(owner.toLowerCase()) ? "me" : owner;
      if (who !== "me") owners.push(owner);
      lines.push(`- [${DONE_WORDS.has(status) ? "x" : " "}] ${action} · ${who}` + (due ? ` · by ${due}` : ""));
    }
    return [lines, owners];
  }

  function readDoc(f) {
    const kind = f.kind, mtime = fromIso(f.modified), text = f.text || "";
    if (kind === "calendar") return readIcs(f, mtime);
    if (kind === "actions") {
      const [lines, owners] = csvRowsToLines(text);
      return { path: f.path, display: f.display, kind, title: stemName(f.display), date: mtime,
        dateSource: "file time (guessed)", lines, people: [], owners, events: [], url: null };
    }
    if (kind === "link") {
      let m = text.match(/^\s*URL\s*=\s*(\S+)/im), url = null;
      if (m) url = m[1];
      else { m = text.match(/https?:\/\/\S+/); if (m) url = m[0]; }
      const title = stemName(f.display);
      return { path: f.path, display: f.display, kind, title, date: mtime, dateSource: "file time (guessed)",
        lines: url ? [`${title} — ${url}`] : [title], people: [], events: [], url };
    }
    const lines = splitLines(text), name = stemName(f.display);
    let date = null, src = "";
    const fm = name.match(/(20\d\d)-(\d\d)-(\d\d)/);
    if (fm) { date = dnum(+fm[1], +fm[2], +fm[3]); if (date !== null) src = "file name"; }
    if (date === null && kind !== "reminders" && kind !== "links") {
      for (const ln of lines.slice(0, 4)) {
        const ds = findDates(ln, mtime);
        if (ds.length && ["iso", "dmy", "d_mon", "mon_d"].includes(ds[0][3]) &&
            (ds[0][0] < 3 || /^\s*(date|when)\b/i.test(ln) || ln.trim().length <= 30)) {
          date = ds[0][2]; src = "first lines"; break;
        }
      }
    }
    if (date === null) { date = mtime; src = "file time (guessed)"; }
    let title = "";
    for (const ln of lines) { const s = ln.trim(); if (s) { title = s.replace(/^#+\s*/, ""); break; } }
    if (!title || ["reminders", "links", "draft"].includes(kind) || title.length > 60) {
      title = name.replace(/^20\d\d-\d\d-\d\d\s*/, "") || name;
    }
    const people = [];
    for (const ln of lines.slice(0, 8)) { const am = ln.match(ATTENDEE_RX); if (am) people.push(...splitNames(am[1])); }
    for (const ln of lines.slice(0, 3)) { const wm = ln.match(/\bw\/\s*(.+)$/); if (wm) people.push(...splitNames(wm[1])); }
    return { path: f.path, display: f.display, kind, title, date, dateSource: src, lines, people, events: [], url: null };
  }

  const icsUnescape = (s) => s.replace(/\\n/g, "\n").replace(/\\N/g, "\n").replace(/\\,/g, ",").replace(/\\;/g, ";").replace(/\\\\/g, "\\");
  function icsDt(v) {
    v = v.trim().replace(/Z+$/, "");
    let m = v.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?$/);
    if (m) return { date: dnum(+m[1], +m[2], +m[3]), h: +m[4], mi: +m[5], s: +(m[6] || 0) };
    m = v.match(/^(\d{4})(\d{2})(\d{2})$/);
    if (m) return { date: dnum(+m[1], +m[2], +m[3]), h: 0, mi: 0, s: 0 };
    return null;
  }
  const startIso = (st) => `${isoDate(st.date)}T${pad(st.h)}:${pad(st.mi)}:${pad(st.s)}`;
  const startLabel = (st) => `${DAY_ABBR[weekday(st.date)]} ${fmtDate(st.date)}, ${pad(st.h)}:${pad(st.mi)}`;

  function readIcs(f, mtime) {
    const raw = (f.text || "").replace(/\r\n/g, "\n");
    const unfolded = raw.replace(/\n[ \t]/g, "").split("\n");
    const events = []; let cur = null, me = null;
    unfolded.forEach((ln, idx) => {
      if (ln.startsWith("BEGIN:VEVENT")) cur = { attendees: [], line: idx + 1 };
      else if (ln.startsWith("END:VEVENT") && cur) { if (cur.start) events.push(cur); cur = null; }
      else if (cur && ln.includes(":")) {
        const i = ln.indexOf(":"), key = ln.slice(0, i), val = ln.slice(i + 1);
        const name = key.split(";")[0].toUpperCase();
        const params = {};
        for (const p of key.split(";").slice(1)) { const j = p.indexOf("="); if (j >= 0) params[p.slice(0, j)] = p.slice(j + 1); }
        if (name === "SUMMARY") cur.title = icsUnescape(val);
        else if (name === "DESCRIPTION") cur.description = icsUnescape(val);
        else if (name === "DTSTART") cur.start = icsDt(val);
        else if (name === "UID") cur.uid = val.trim();
        else if (name === "ATTENDEE") cur.attendees.push(strip(params.CN || val.replace("mailto:", ""), '"'));
        else if (name === "ORGANIZER") me = strip(params.CN || "", '"') || me;
      }
    });
    for (const e of events) {
      e.id = e.uid || `${startIso(e.start)}-${e.title || ""}`;
      e.date = e.start.date;
      e.me = me;
    }
    return { path: f.path, display: f.display, kind: "calendar", title: baseName(f.display), date: mtime,
      dateSource: "file time (guessed)", lines: unfolded, people: [], events, url: null };
  }

  const readAll = (inv) => inv.filter((f) => f.allowed).map(readDoc);

  // ------------------------------------------------------------------ words
  const STOP = setOf(`a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those i me my we our you your he she they them his her their there here not no yes do
does did have has had will would should could can may might just also very really about into over under
than too up down out off again more most some any each all both few other such only own same s t d ll m
re ve don didn im ive ill weve were lets per via vs etc ok okay what when where who whom which why how
w hmm tho though pls please get got go going make made one two us once before after basically actually
haven hasn hasnt havent didn isn wasn won can couldn shouldn wouldn aren weren yet ago she he her him
still sure back came come`.split(/\s+/));
  const GENERIC = setOf(`meeting meet call sync notes note update quick thing things stuff today said says say need needs want
wants like think thinks new also still now next first end time sure day days week weeks month group
agenda date dates item items catch chat oneonone weekly daily standup check checkin session discussion
review talk topic plan planning team context thanks follow followup again since ask asked know start`.split(/\s+/));
  const PHRASES = [
    [/\b1\s*[:\-]\s*1s?\b|\bone[ -]?(?:on|to)[ -]?one\b/gi, " oneonone "],
    [/\btech[ -]?lead\b|\btl\b/gi, " techlead "],
    [/\bsingle sign[ -]?on\b/gi, " sso "],
    [/\bpurchase order\b/gi, " po "],
    [/\bgo[ -]?live\b/gi, " launch "],
    [/\bf\/u\b|\bfollow[ -]?up\b/gi, " followup "],
    [/\bw\//gi, " with "],
    [/\beow\b|\bend of (?:the )?week\b/gi, " endofweek "],
    [/\bsign[ -]?off\b/gi, " signoff "],
    [/\bon[ -]?call\b/gi, " oncall "],
  ];
  const SYN = { supplier: "vendor", suppliers: "vendor", vendors: "vendor", provider: "vendor",
    cost: "budget", costs: "budget", spend: "budget", funding: "budget", money: "budget",
    price: "pricing", prices: "pricing", priced: "pricing", quoted: "pricing", quote: "pricing",
    discount: "pricing", expensive: "pricing", cheap: "pricing", cheaper: "pricing",
    hire: "hiring", hires: "hiring", headcount: "hiring", recruit: "hiring", recruiting: "hiring",
    release: "launch", launching: "launch", launched: "launch", live: "launch",
    delay: "slip", delayed: "slip", postpone: "slip", postponed: "slip", push: "slip", pushed: "slip",
    mtg: "meeting", mtgs: "meeting", meetings: "meeting", convo: "conversation", conversations: "conversation",
    promotion: "techlead", promo: "techlead", wks: "week", wk: "week", weeks: "week", hrs: "hour", hr: "hour",
    hours: "hour", mgr: "manager", db: "database", onboard: "onboarding", onboarded: "onboarding",
    starter: "onboarding", starts: "start", started: "start", starting: "start", "api's": "api", apis: "api",
    limits: "limit", decided: "decision", decide: "decision" };

  function stem(w) {
    if (Object.prototype.hasOwnProperty.call(SYN, w)) w = SYN[w];
    if (w.length <= 4 || !isAlpha(w)) return w;
    for (const suf of ["ings", "ing", "edly", "ed", "ies", "es", "s"]) {
      if (w.endsWith(suf) && w.length - suf.length >= 3) { w = w.slice(0, -suf.length) + (suf === "ies" ? "y" : ""); break; }
    }
    if (w.length > 4 && w.endsWith("e")) w = w.slice(0, -1);
    return w;
  }
  const TOKEN_RX = /[a-z0-9£$€]+(?:'[a-z]+)?/g;
  function tokens(text) {
    let t = text.toLowerCase();
    for (const [rx, rep] of PHRASES) t = t.replace(rx, rep);
    const out = [];
    for (const m of t.matchAll(TOKEN_RX)) {
      const w = m[0].split("'")[0];
      if (!w || STOP.has(w)) continue;
      out.push(stem(w));
    }
    return out;
  }

  // ------------------------------------------------------------------ tagging
  const NEG_RX = /\b(not|n't|haven'?t|hasn'?t|hasnt|havent|didn'?t|didnt|isn'?t|isnt|wasn'?t|still|yet to|pending|partly|partially|waiting)\b|\?/i;
  const DONE_RX = /\[x\]|✅|✔|☑|\b(done|sent|completed?|sorted|closed|scoped|raised|fixed|resolved|booked|shipped|delivered|submitted|finished)\b/i;
  const DECISION_RX = /\b(decision|decided|agreed|going with|go with|approved|signed off|settled on|chose|chosen|confirmed|final call|green ?lit|said yes)\b/i;
  const NOT_A_DECISION_RX = /\bneed(?:s)?\s+(?:a|an|to)\b[^.]*\b(decision|decide)\b|\bpending\s+decision\b/i;
  const QUESTION_RX = /\?|\b(tbd|tbc|open question|unclear|not sure|unknown|to be confirmed|who owns|find out)\b/i;
  const RISK_RX = /\b(at risk|risk(?! summary)|blockers?|blocked|concern(?:ed)?|worried|worry|problem|issue|slipp?(?:ing|ed)?|delay(?:ed)?|behind|burnout|tight|freeze)\b/i;
  const ACTION_RX = [
    [/^\s*(?:[-*•]\s*)?\[\s\]/, "unticked box"],
    [/^\s*(?:[-*•]\s*)?(?:ai|a\/i|action|todo|to-do|next|follow[ -]?up|f\/u)\s*:/i, "action label"],
    [/\b(need to|needs to|i'll|i will|i said i'd|i said i would|remember to|don't forget|chase|to do|must)\b/i, "says it needs doing"],
    [/^\s*(?:[-*•]\s*)?(?:me|i)\s*(?::|-|to\b)/i, "assigned to you"],
    [/\b(?:ask|check w(?:ith|\/)?)\s+\w+/i, "says to ask someone"],
    [/^\s*(?:[-*•]\s*)?\w+\s*:\s*wants\b|\bwants\b.*\b(summary|update|report|plan|deck|doc)\b/i, "someone asked you for it"],
    [/\bdue\b/i, "has a due date"],
  ];
  const DECISION_NEG_RX = /\b(not|n't|hasnt|havent|didnt|isnt|wasnt|still|yet)\b|\?/i;
  const CHANGE_RX = /\b(instead|reversed|no longer|changed|scrap(?:ped)?|switch(?:ed)? to|push(?:ed)? (?:back|to)|move[ds]? (?:\w+ )?to|moving to|on hold|paused|revised|freeze|cancel(?:led)?|dropped)\b/i;
  const MONEY_RX = /(?<![\w.])([£$€])?\s?(\d+(?:\.\d+)?)\s?(k|m|bn)\b|([£$€])\s?(\d[\d,]*(?:\.\d+)?)/gi;
  const URL_RX = /https?:\/\/[^\s)>\]]+/;
  const SECTION_RX = /^\s*(?:#+\s*)?(actions?|action items|next steps|to ?dos?|open q\w*|questions|decisions?|risks?|asks?)\s*:?\s*$/i;
  const SELF_RX = /\b(i'll|i will|i said i'd|i said i would|i need to|i haven't|need to do this)\b|^\s*(?:[-*•]\s*)?(?:\[.\]\s*)?(?:me|i)\s*(?::|-|to\b)|\b(?:ai|action)\s*:\s*me\b/i;
  const DATEISH = /^\s*(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*\s+)?\d{1,2}(?:\/\d{1,2}\/\d{2,4}|\s+\w+\s+20\d\d)\s*$/i;

  function moneyValues(text) {
    const out = [];
    for (const m of text.matchAll(MONEY_RX)) {
      let v;
      if (m[2] !== undefined) {
        if (!m[1] && !m[3]) continue;
        v = parseFloat(m[2]) * ({ k: 1e3, m: 1e6, bn: 1e9 }[(m[3] || "").toLowerCase()] || 1);
      } else v = parseFloat(m[5].replace(/,/g, ""));
      out.push([m.index, v]);
    }
    return out;
  }
  const fmtG = (x) => String(Number(x.toPrecision(6)));
  const moneyStr = (v) => (v >= 1000 ? `£${fmtG(v / 1000)}k` : `£${fmtG(v)}`);
  const clean = (line) => line.replace(/^\s*(?:[-*•]\s*)?(?:\[[ xX]\]\s*)?/, "").replace(/^#+\s*/, "").split("**").join("").trim();

  class Roster {
    constructor() { this.full = new Map(); this.me = null; }
    add(name) {
      name = name.trim();
      if (!name || ["me", "i", "myself", "you"].includes(name.toLowerCase())) return;
      const first = strip(name.split(/\s+/)[0], ".,()").toLowerCase();
      if (first.length < 2 || !/^\p{L}+$/u.test(first) || STOP.has(first)) return;
      if (!this.full.has(first) || name.length > this.full.get(first).length) {
        this.full.set(first, name.includes(" ") ? name : capitalize(name));
      }
    }
    has(first) { return this.full.has(first); }
    inText(text) {
      const low = text.toLowerCase(), out = new Set();
      for (const f of this.full.keys()) if (new RegExp(`\\b${esc(f)}\\b`).test(low)) out.add(f);
      return out;
    }
    name(first) {
      if (first === null || first === undefined) return "unassigned";
      if (first === "you") return "You";
      return (this.full.get(first) || capitalize(first)).split(/\s+/)[0];
    }
  }

  function buildRoster(docs) {
    const r = new Roster();
    for (const d of docs) {
      for (const p of d.people.concat(d.owners || [])) r.add(p);
      for (const e of d.events) { for (const a of e.attendees) r.add(a); if (e.me) r.me = e.me; }
      if (d.kind !== "calendar") {
        for (const ln of d.lines) for (const m of ln.matchAll(/(?<![\w.])@([A-Za-z]{2,})\b(?![.@])/g)) r.add(m[1]);
      }
    }
    if (r.me) r.full.delete(r.me.split(/\s+/)[0].toLowerCase());
    return r;
  }

  function buildFrags(docs, roster) {
    const frags = [];
    for (const d of docs) {
      if (d.kind === "calendar") continue;
      let section = "";
      d.lines.forEach((raw, idx) => {
        const i = idx + 1, s = raw.trim();
        if (!s) return;
        if (i <= 3 && (lstrip(s, "# ").trim() === d.title.trim() || DATEISH.test(s) ||
            (/\bw\/\s*[A-Z]/.test(s) && findDates(s, d.date).length))) return;
        if (/^\s*(attendees|with|people|present|date|when|draft)\b/i.test(s) && i <= 4) return;
        const sm = s.match(SECTION_RX);
        if (sm) { section = sm[1].toLowerCase(); return; }
        if (s.startsWith("#") || s === "-" || s === "*") { section = s.startsWith("#") ? "" : section; return; }
        if (s.startsWith("[InternetShortcut]")) return;
        const text = clean(raw);
        if (text.length < 3) return;
        let date = d.date, guessed = d.dateSource.startsWith("file time");
        const lead = findDates(text.slice(0, 22), d.date);
        if (lead.length && ["iso", "dmy", "d_mon", "mon_d"].includes(lead[0][3]) && lead[0][0] < 3) {
          date = lead[0][2]; guessed = false;
        }
        const f = { id: frags.length, doc: d, line: i, raw, text, date, dateGuessed: guessed, section,
          toks: tokens(text), tags: new Set(), why: {}, owner: null, due: null, people: new Set(), money: [],
          dates: [], url: null };
        tag(f, d, roster);
        frags.push(f);
      });
    }
    return frags;
  }

  function tag(f, d, roster) {
    const t = f.text, raw = f.raw;
    f.people = roster.inText(t);
    f.money = moneyValues(t);
    f.dates = findDates(t, f.date).map(([s, , dd, k]) => [s, dd, k]);
    const u = t.match(URL_RX);
    if (u || d.kind === "link" || d.kind === "links") {
      f.url = u ? u[0] : d.url;
      if (f.url) { f.tags.add("link"); f.why.link = "a saved link"; return; }
    }
    const negated = NEG_RX.test(t);
    let m = raw.match(DONE_RX);
    if (m && !(negated && !["[x]", "[X]", "✅", "✔", "☑"].includes(m[0]))) {
      f.tags.add("done"); f.why.done = `says “${m[0]}”`;
    }
    m = t.match(DECISION_RX);
    if (m && !NOT_A_DECISION_RX.test(t) && !DECISION_NEG_RX.test(t)) {
      f.tags.add("decision"); f.why.decision = `says “${m[0]}”`;
      if (/\bpending\b|\bif\b|\bsubject to\b/i.test(t)) f.tags.add("tentative");
    }
    m = t.match(QUESTION_RX);
    if (m || f.section.startsWith("open q") || f.section.startsWith("question")) {
      f.tags.add("question");
      f.why.question = m && m[0] !== "?" ? `says “${m[0]}”` : m ? "ends with a question mark" : "listed under open questions";
    }
    m = t.match(RISK_RX);
    if (m) { f.tags.add("risk"); f.why.risk = `says “${m[0]}”`; }
    if (!f.tags.has("done")) {
      let reason = null;
      if (["action", "next", "to"].some((p) => f.section.startsWith(p))) reason = `listed under “${f.section}”`;
      if (!reason) for (const [rx, label] of ACTION_RX) if (rx.test(raw)) { reason = label; break; }
      if (!reason) {
        for (const first of roster.full.keys()) {
          if (new RegExp(`\\b${first}\\s+(?:to|will|needs to|should)\\s+(?!be\\b)\\w+`, "i").test(t)) {
            reason = `says ${roster.name(first)} will do something`; break;
          }
        }
      }
      if (!reason && d.kind === "reminders") reason = "in your reminders";
      if (reason) { f.tags.add("action"); f.why.action = reason; }
    }
    if (d.kind === "actions" && t.includes(" · ")) {
      const who = t.split(" · ")[1].trim().toLowerCase();
      f.owner = ["me", "i", "you"].includes(who) ? "you" : (who.split(/\s+/)[0] || null);
    }
    if (f.owner === null && (f.tags.has("action") || f.tags.has("done") || f.tags.has("question"))) {
      for (const first of roster.full.keys()) {
        if (new RegExp(`(?:^|[\\s(@])${first}\\s+(?:to|will|needs to|should)\\s+(?!be\\b)\\w+`, "i").test(t)) { f.owner = first; break; }
      }
      if (f.owner === null && (SELF_RX.test(raw) || d.kind === "reminders" || /\b(chase|ask|check w)\b/i.test(t) ||
          (/\bwants\b/i.test(t) && f.tags.has("action")))) f.owner = "you";
      if (f.owner === null && f.tags.has("action") && !d.people.length && (d.kind === "note" || d.kind === "reminders")) f.owner = "you";
    }
    if (f.tags.has("action")) {
      const dm = t.match(/\b(?:by|before|until|due)\b/i);
      if (dm) { const after = f.dates.filter(([s]) => s >= dm.index).map(([, dd]) => dd); if (after.length) f.due = after[0]; }
    }
  }

  // ------------------------------------------------------------------ scoring
  const CAP_RX = /(?<![.!?:]\s)(?<!^)(?<![.!?:])\b([A-Z][a-z]{2,})\b/g;
  const MONTHS_AND_DAYS = setOf(`jan feb mar apr may jun jul aug sep sept oct nov dec january february march
april june july august september october november december mon tue wed thu fri sat sun monday tuesday
wednesday thursday friday saturday sunday the this that and but quick`.split(/\s+/));
  const NOT_ENT = MONTHS_AND_DAYS;

  class Index {
    constructor(frags, roster) {
      this.frags = frags; this.roster = roster; this.N = Math.max(1, frags.length);
      this.df = new Map();
      for (const f of frags) for (const w of new Set(f.toks)) this.df.set(w, (this.df.get(w) || 0) + 1);
      this.avgdl = frags.length ? sum(frags.map((f) => f.toks.length)) / this.N : 1.0;
      this.ent = new Set();
      for (const f of frags) for (const m of f.text.matchAll(CAP_RX)) {
        const w = m[1].toLowerCase();
        if (!NOT_ENT.has(w) && !roster.has(w)) this.ent.add(stem(w));
      }
    }
    idf(w) { const df = this.df.get(w) || 0; return Math.log(1 + (this.N - df + 0.5) / (df + 0.5)); }
    weight(w) {
      if (GENERIC.has(w) || isDigits(w)) return 0.25 * this.idf(w);
      if (this.roster.has(w)) return 0.6 * this.idf(w);
      if (/^[£$€]?\d/.test(w)) return 0.3 * this.idf(w);
      return this.idf(w);
    }
    bm25(q, f, k1 = 1.2, b = 0.6) {
      if (!q.size) return 0.0;
      const tf = new Map();
      for (const w of f.toks) tf.set(w, (tf.get(w) || 0) + 1);
      const dl = f.toks.length || 1;
      let s = 0.0;
      for (const [w, qw] of q) {
        const n = tf.get(w) || 0;
        if (n) s += qw * this.idf(w) * n * (k1 + 1) / (n + k1 * (1 - b + b * dl / this.avgdl));
      }
      return s;
    }
    sim(a, b) {
      const A = new Set(a.toks), B = new Set(b.toks), shared = inter(A, B);
      if (!shared.size || all(shared, (w) => GENERIC.has(w) || this.roster.has(w) || /^\d/.test(w))) return 0.0;
      const wa = sum([...A].map((w) => this.weight(w))) || 1;
      const wb = sum([...B].map((w) => this.weight(w))) || 1;
      return sum([...shared].map((w) => this.weight(w))) / Math.min(wa, wb);
    }
  }

  // ------------------------------------------------------------------ threads
  function buildThreads(ix, kinds, threshold = 0.42) {
    const pool = sortBy(ix.frags.filter((f) => any(kinds, (k) => f.tags.has(k))), (f) => [f.date, f.id]);
    const parent = pool.map((_, i) => i);
    const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) {
      if (ix.sim(pool[i], pool[j]) >= threshold) parent[find(i)] = find(j);
    }
    const comp = new Map();
    pool.forEach((f, i) => { const r = find(i); if (!comp.has(r)) comp.set(r, []); comp.get(r).push(f); });
    const out = [];
    for (const grp of comp.values()) {
      const gs = sortBy(grp, (f) => [f.date, f.id]);
      const tags = unionAll(gs.map((f) => f.tags));
      const kind = tags.has("action") ? "action" : tags.has("question") ? "question" :
        tags.has("decision") ? "decision" : tags.has("risk") ? "risk" : "done";
      out.push({ frags: gs, kind, first: gs[0], last: gs[gs.length - 1] });
    }
    return out;
  }
  function threadStatus(t) {
    const latest = maxBy(t.frags, (f) => [f.date, f.id]);
    const sameDay = t.frags.filter((f) => f.date === latest.date);
    if (sameDay.some((f) => f.tags.has("done")) &&
        !sameDay.some((f) => (f.tags.has("action") || f.tags.has("question")) && !f.tags.has("done"))) return "done";
    return "open";
  }
  const threadOwner = (t) => { for (let i = t.frags.length - 1; i >= 0; i--) if (t.frags[i].owner) return t.frags[i].owner; return null; };
  const threadDue = (t) => { const ds = t.frags.filter((f) => f.due !== null).map((f) => f.due); return ds.length ? Math.max(...ds) : null; };

  // ------------------------------------------------------------------ changes
  const SUBJECT_STOP = setOf(`confirm confirmed approve approved agree agreed decision send sent raise raised ask
move moving moved push need want expect remember check chase said think new revise revised now target update sign
signoff go going start get set open close done due only cover covers top extra higher more less over under year
month week day end anything original amount`.split(/\s+/).map(stem));
  const near = (f, pos, span = 26) => new Set(tokens(f.text.slice(Math.max(0, pos - span), pos + span))
    .filter((w) => !GENERIC.has(w) && !/^\d/.test(w) && !"£$€".includes(w[0]) && !NOT_ENT.has(w)));
  const entities = (ix, f, n) => { const e = inter(n, ix.ent); return e.size ? e : inter(new Set(tokens(f.doc.title)), ix.ent); };
  function valued(f) {
    const out = f.money.map(([p, v]) => ["money", v, near(f, p)]);
    for (const [p, d, k] of f.dates) {
      if (["iso", "dmy", "d_mon", "mon_d"].includes(k) && !(p < 3 && d === f.date)) out.push(["date", d, near(f, p)]);
    }
    return out;
  }
  const vfmt = (kind, v) => (kind === "money" ? moneyStr(v) : fmtDate(v));

  function findChanges(ix, frags) {
    frags = frags || ix.frags;
    const cand = frags.filter((f) => !f.tags.has("link"));
    const names = new Set(ix.roster.full.keys());
    const vals = new Map(cand.map((f) => [f.id, valued(f)]));
    const pairs = [];
    for (let i = 0; i < cand.length; i++) for (let j = i + 1; j < cand.length; j++) {
      const a = cand[i], b = cand[j];
      const [old, nw] = cmpKey([a.date, a.id], [b.date, b.id]) <= 0 ? [a, b] : [b, a];
      if (old.date === nw.date) continue;
      const s = ix.sim(a, b);
      if (s < 0.22) continue;
      let found = null;
      outer: for (const [k1, v1, n1] of vals.get(old.id)) {
        for (const [k2, v2, n2] of vals.get(nw.id)) {
          const subj = minus(minus(inter(n1, n2), names), SUBJECT_STOP);
          if (k1 !== k2 || !subj.size) continue;
          const e1 = entities(ix, old, n1), e2 = entities(ix, nw, n2);
          if (e1.size && e2.size && !inter(e1, e2).size) continue;
          if (v1 === v2) { found = "agree"; break outer; }
          found = found || [k1, subj];
        }
      }
      if (found && found !== "agree") {
        const top = maxBy([...found[1]], (w) => [ix.idf(w), w]);
        pairs.push([old, nw, found[0], found[1], `${found[0]}|${top}`, found[1]]);
        continue;
      }
      const m = nw.text.match(CHANGE_RX);
      const shared = new Set([...inter(new Set(old.toks), new Set(nw.toks))].filter((w) =>
        !GENERIC.has(w) && !names.has(w) && !/^\d/.test(w) && !SUBJECT_STOP.has(w)));
      if (m && old.tags.has("decision") && s >= 0.45 && shared.size >= 2) pairs.push([old, nw, "said", m[0], `said|${old.id}`, shared]);
    }
    const stories = new Map();
    for (const p of pairs) { if (!stories.has(p[4])) stories.set(p[4], []); stories.get(p[4]).push(p); }
    const out = [];
    for (const group of stories.values()) {
      const byId = new Map();
      for (const p of group) for (const f of [p[0], p[1]]) byId.set(f.id, f);
      const members = sortBy([...byId.values()], (f) => [f.date, f.id]);
      const counts = {};
      for (const p of group) counts[p[2]] = (counts[p[2]] || 0) + 1;
      const kind = Object.keys(counts).reduce((x, y) => (counts[y] > counts[x] ? y : x));
      const nonDraft = members.filter((m) => m.doc.kind !== "draft");
      let nw = (nonDraft.length ? nonDraft : members).slice(-1)[0], old, reason;
      if (kind === "said") {
        const said = group.filter((p) => p[2] === "said");
        old = said[0][0];
        nw = maxBy(said.map((p) => p[1]), (f) => [f.date, f.id]);
        reason = `later note says “${said[said.length - 1][3]}”`;
      } else {
        const subject = unionAll(group.filter((p) => p[2] === kind).map((p) => p[3]));
        const seq = [];
        for (const m of members) {
          for (const [k, v, n] of vals.get(m.id)) {
            if (k === kind && inter(n, subject).size) { if (!seq.length || seq[seq.length - 1] !== v) seq.push(v); break; }
          }
        }
        if (seq.length < 2) continue;
        const firstV = seq[0];
        const holders = members.filter((m) => vals.get(m.id).some(([k, v, n]) => k === kind && v === firstV && inter(n, subject).size));
        old = [...holders].reverse().find((m) => m.tags.has("decision")) || (holders.length ? holders[holders.length - 1] : members[0]);
        reason = seq.map((v) => vfmt(kind, v)).join(" → ");
      }
      if (old === nw) continue;
      out.push({ old, new: nw, members, reason, kind, tentative: nw.tags.has("tentative"),
        subject: unionAll(group.map((p) => p[5])) });
    }
    return out.sort((x, y) => y.new.date - x.new.date);
  }

  // ------------------------------------------------------------------ presenting
  const src = (f) => ({ path: f.doc.path, file: f.doc.display, title: f.doc.title, kind: f.doc.kind, line: f.line,
    date: isoDate(f.date), date_label: fmtDate(f.date), date_guessed: f.dateGuessed });
  function whyText(f, matched, extra = "") {
    const bits = [];
    if (matched && matched.length) bits.push("mentions " + matched.slice(0, 3).map((w) => `“${w}”`).join(", "));
    const labels = { decision: "counted as a decision", action: "counted as an action", question: "counted as open",
      risk: "counted as a risk", done: "counted as done" };
    for (const tg of ["decision", "action", "question", "risk", "done"]) {
      if (tg in f.why) { bits.push(`${labels[tg]} because it ${f.why[tg]}`); break; }
    }
    if (f.dateGuessed) bits.push("no date in this file, so I used the file's last-changed date");
    if (extra) bits.push(extra);
    const s = bits.join("; ");
    return s ? cap1(s) : "";
  }
  const item = (f, { why = "", flags = [], confidence = "high", extraSources = [], headline = null } = {}) => ({
    text: f.text, headline, source: src(f), more_sources: extraSources.filter((x) => x !== f).map(src),
    why, flags, confidence });
  const days = (a, b) => b - a;
  const matched = (q, f) => sortBy([...q.keys()], (w) => [-q.get(w)]).filter((w) => f.toks.includes(w));

  // ------------------------------------------------------------------ meetings
  function listMeetings(docs, today) {
    const evs = [];
    for (const d of docs) for (const e of d.events) {
      evs.push({ id: e.id, title: e.title || "(no title)", start: startIso(e.start), date_label: startLabel(e.start),
        attendees: e.attendees.filter((a) => a !== e.me), description: e.description || "",
        upcoming: e.date >= today, file: d.display });
    }
    const up = sortBy(evs.filter((e) => e.upcoming), (e) => [e.start]);
    const past = sortBy(evs.filter((e) => !e.upcoming), (e) => [e.start]).reverse();
    return up.concat(past);
  }

  function meetingBrief(docs, eventId, today, context) {
    let event = null;
    for (const d of docs) for (const e of d.events) if (e.id === eventId) event = e;
    if (!event) return { error: "I couldn't find that meeting in the calendar files you've allowed." };
    return brief(docs, event, today, context);
  }

  function brief(docs, event, today, context) {
    const roster = buildRoster(docs);
    const when = event.date;
    const ref = when >= today ? Math.min(today, when) : when;
    const attendees = event.attendees.filter((a) => a !== event.me);
    const people = new Set(attendees.map((a) => a.split(/\s+/)[0].toLowerCase()));
    for (const a of attendees) roster.add(a);
    const frags = buildFrags(docs, roster).filter((f) => f.date <= when);
    const ix = new Index(frags, roster);
    const titleToks = tokens(event.title || "").filter((w) => !GENERIC.has(w) && !people.has(w));
    const agendaRaw = (event.description || "").replace(/^\s*agenda\s*:\s*/i, "");
    const agendaItems = agendaRaw.split(/,|;|\n|\band\b/).map((a) => a.trim()).filter(Boolean);
    const agendaToks = tokens(agendaRaw).filter((w) => !GENERIC.has(w) && !people.has(w));
    const topic = new Map(titleToks.map((w) => [w, 1.0]));
    for (const w of agendaToks) topic.set(w, Math.max(topic.get(w) || 0, 0.8));
    const oneToOne = people.size === 1;

    const rawTopic = new Map(frags.map((f) => [f.id, ix.bm25(topic, f)]));
    const mx = Math.max(0, ...rawTopic.values()) || 1;
    const rel = new Map();
    for (const f of frags) {
      let s = 2.0 * rawTopic.get(f.id) / mx;
      if (inter(f.people, people).size) s += 1.5;
      const docPeople = new Set([...f.doc.people.map((p) => p.split(/\s+/)[0].toLowerCase()),
        ...tokens(f.doc.title).filter((w) => roster.has(w))]);
      if (inter(docPeople, people).size) {
        const share = inter(docPeople, people).size / Math.max(1, minus(docPeople, new Set(["me"])).size);
        s += 1.2 * Math.min(1.0, share) + (oneToOne && tokens(f.doc.title).some((w) => people.has(w)) ? 1.0 : 0);
      }
      s += 0.3 * Math.max(0.0, 1 - days(f.date, when) / 60);
      rel.set(f.id, s);
    }
    const relevant = new Set([...rel].filter(([, s]) => s >= 1.1).map(([id]) => id));
    const sections = [];

    // last time you met
    let lastDoc = null, lastScore = 0.0;
    for (const d of docs) {
      if (d.kind !== "note" || d.date >= when) continue;
      const dp = new Set([...d.people.map((p) => p.split(/\s+/)[0].toLowerCase()), ...tokens(d.title).filter((w) => roster.has(w))]);
      let s = inter(dp, people).size / Math.max(1, people.size) +
        0.8 * inter(new Set(tokens(d.title)), new Set(titleToks)).size;
      if (oneToOne && !inter(dp, people).size) s = 0;
      if (s > lastScore || (s === lastScore && lastDoc && d.date > lastDoc.date && s > 0)) { lastDoc = d; lastScore = s; }
    }
    if (lastDoc && lastScore >= 0.5) {
      const lf = frags.filter((f) => f.doc === lastDoc && ["decision", "action", "risk", "question"].some((t) => f.tags.has(t))).slice(0, 4);
      sections.push({ id: "last", title: `Last time: ${lastDoc.title}, ${fmtDate(lastDoc.date)}`,
        subtitle: `${plural(days(lastDoc.date, when), "day")} before this meeting`,
        items: lf.map((f) => item(f, { why: whyText(f) })) });
    }

    // what changed
    const changes = findChanges(ix).filter((c) => c.members.some((m) => relevant.has(m.id)));
    const chItems = changes.slice(0, 5).map((c) => ({
      text: c.new.text, headline: `Changed: ${c.reason}` + (c.tentative ? " (not final yet)" : ""),
      before: { text: c.old.text, source: src(c.old) }, source: src(c.new),
      more_sources: c.members.filter((m) => m !== c.old && m !== c.new).map(src),
      why: `Your notes from ${fmtDate(c.old.date)} and ${fmtDate(c.new.date)} talk about the same thing but say different things; the newer one is shown first. Check which is current.`,
      flags: ["changed"].concat(c.tentative ? ["tentative"] : []), confidence: "medium" }));
    if (chItems.length) sections.push({ id: "changed", title: "What's changed since it was agreed", subtitle: "Older notes may be out of date", items: chItems });
    const changedIds = new Set(changes.flatMap((c) => c.members.map((m) => m.id)));

    // open promises and actions
    const actItems = [], qItems = [];
    for (const t of buildThreads(ix, ["action", "question", "done"])) {
      if (!t.frags.some((f) => relevant.has(f.id))) continue;
      if (threadStatus(t) === "done") continue;
      const owner = threadOwner(t), due = threadDue(t), age = days(t.first.date, ref);
      const flags = [];
      if (due !== null && due < ref) flags.push(`overdue ${plural(days(due, ref), "day")}`);
      else if (due !== null) flags.push(`due ${fmtDate(due)}`);
      if (t.frags.length > 1) flags.push(`written down ${t.frags.length} times`);
      const involved = people.has(owner) || inter(unionAll(t.frags.map((f) => f.people)), people).size > 0;
      const score = sum(t.frags.map((f) => rel.get(f.id))) / t.frags.length + 0.4 * (t.frags.length - 1) +
        (flags.length && flags[0].startsWith("overdue") ? 1.0 : 0) + (owner === "you" && involved ? 0.8 : 0);
      let headline, bucket;
      if (t.kind === "action") {
        headline = owner === "you" ? `You: open for ${plural(age, "day")} (since ${fmtDate(t.first.date)})`
          : `${roster.name(owner)}: open since ${fmtDate(t.first.date)}`;
        bucket = actItems;
      } else { headline = `Unanswered since ${fmtDate(t.first.date)}`; bucket = qItems; }
      const show = (owner === "you" && t.kind === "action") || t.kind === "question" ? t.first
        : maxBy(t.frags, (f) => [f.toks.length >= 3, f.date, f.id]);
      const it = item(show, { why: whyText(show, null, t.frags.length > 1 ? `I linked ${t.frags.length} notes that talk about the same thing` : ""),
        flags, extraSources: t.frags, headline, confidence: t.frags.length > 1 || show.owner ? "high" : "medium" });
      it.owner = roster.name(owner);
      it._score = score;
      bucket.push(it);
    }
    for (const [bucket, sid, title, sub] of [
      [actItems, "actions", "Open promises and actions", "Nothing in your notes says these are done"],
      [qItems, "questions", "Still unanswered", "Raised before, never answered in your notes"]]) {
      const sorted = sortBy(bucket, (x) => [-x._score]);
      sorted.forEach((x) => delete x._score);
      if (sorted.length) sections.push({ id: sid, title, subtitle: sub, items: sorted.slice(0, 6), more: Math.max(0, sorted.length - 6) });
    }

    // decisions on record
    const dec = sortBy(frags.filter((f) => f.tags.has("decision") && relevant.has(f.id) && !changedIds.has(f.id)), (f) => [-rel.get(f.id), f.date]);
    if (dec.length) {
      sections.push({ id: "decisions", title: "Decisions on record", subtitle: "Nothing later contradicts these",
        items: sortBy(dec.slice(0, 5), (f) => [f.date]).map((f) => item(f, { why: whyText(f), flags: f.tags.has("tentative") ? ["not final"] : [] })) });
    }

    // unfinished drafts
    const drafts = draftGaps(docs, frags, ix, people, topic, roster);
    if (drafts.length) sections.push({ id: "drafts", title: "You started this but didn't finish", subtitle: "Your other notes may already have the missing parts", items: drafts });

    // links you saved
    const expand = new Map(topic);
    for (const f of sortBy(frags.filter((f) => relevant.has(f.id) && !f.tags.has("link")), (f) => [-rel.get(f.id)]).slice(0, 8)) {
      for (const w of f.toks) if (!GENERIC.has(w) && !roster.has(w) && !/^\d/.test(w)) expand.set(w, Math.max(expand.get(w) || 0, 0.35));
    }
    const links = sortBy(frags.filter((f) => f.tags.has("link")).map((f) => [ix.bm25(expand, f), f])
      .filter(([s, f]) => s > 1.0 && (f.toks.some((w) => topic.has(w)) || inter(new Set(f.toks), new Set(expand.keys())).size >= 2)), (x) => [-x[0]]);
    if (links.length) {
      sections.push({ id: "links", title: "Links you saved that look related", subtitle: "Shown, never opened - the assistant does not go online",
        items: links.slice(0, 3).map(([, f]) => Object.assign(item(f, { why: whyText(f, matched(expand, f)) }), { url: f.url })) });
    }

    // what I couldn't check
    const gaps = [];
    if (people.size && !sections.some((s) => s.id === "last")) {
      gaps.push({ text: `I found no earlier meeting notes with ${[...people].sort().map((p) => roster.name(p)).join(", ")}${titleToks.length ? " about this" : ""}, so there's no “last time” to recap.`, kind: "history" });
    }
    for (const p of [...people].sort()) {
      const n = frags.filter((f) => f.people.has(p) || f.doc.people.some((x) => x.split(/\s+/)[0].toLowerCase() === p)).length;
      if (n === 0) gaps.push({ text: `I found nothing about ${roster.name(p)} in your notes.`, kind: "person" });
      else if (n <= 2) gaps.push({ text: `Only ${plural(n, "note")} mention ${roster.name(p)}, so this brief may be thin on them.`, kind: "person" });
    }
    for (const a of agendaItems) {
      const at = tokens(a).filter((w) => !GENERIC.has(w));
      if (at.length && !frags.some((f) => at.every((w) => f.toks.includes(w)))) gaps.push({ text: `The agenda mentions “${a}” but I found nothing about it.`, kind: "agenda" });
    }
    gaps.push(...unreadableGaps(context, frags));
    const usedGuessed = [...new Set(frags.filter((f) => f.dateGuessed && relevant.has(f.id)).map((f) => f.doc.display))].sort();
    if (usedGuessed.length) gaps.push({ text: `No dates inside ${usedGuessed.join(", ")}, so I went by when the file was last changed. Treat the timing of those notes with care.`, kind: "dates" });
    if ((context.switched_off || []).length) {
      gaps.push({ text: `You switched off ${plural(context.switched_off.length, "file")} (${context.switched_off.slice(0, 3).join(", ")}), so I didn't look at them.`, kind: "scope" });
    }
    sections.push({ id: "gaps", title: "What I couldn't check", subtitle: "So you know where this brief stops",
      items: gaps.length ? gaps : [{ text: "Nothing obvious is missing. All the files you allowed were readable.", kind: "ok" }], plain: true });

    return { meeting: { title: event.title, date_label: event.date_label || startLabel(event.start), attendees, agenda: agendaItems },
      talking_points: talkingPoints(sections, roster, people), sections,
      stats: { lines_considered: frags.length, lines_used: relevant.size } };
  }

  function unreadableGaps(context, frags) {
    const out = [];
    for (const name of context.unreadable || []) {
      const stemWords = new Set(tokens(name.replace(/\d/g, " ")).filter((w) => !["png", "jpg", "jpeg"].includes(w)));
      const refs = frags.filter((f) => inter(stemWords, new Set(f.toks)).size || /\b(screenshot|pic|photo|image)s?\b/i.test(f.text));
      const extra = refs.length ? ` Your note “${refs[0].text}” (${fmtDate(refs[0].date)}) points to it, so something relevant may be in it.` : "";
      out.push({ text: `I can't read images on this device yet, so I skipped ${name}.${extra}`, kind: "unreadable", source: refs.length ? src(refs[0]) : null });
    }
    return out;
  }

  const INCOMPLETE_RX = /(\bbecause|\band|\bbut|\bso|:|-|—|,)\s*$|\[?\btodo\b|\btbd\b|\bxx+\b|\[\s*\]|\?\?\?/i;
  function draftGaps(docs, frags, ix, people, topic, roster) {
    const out = [];
    const pool = frags.filter((f) => !["draft", "links", "link"].includes(f.doc.kind));
    for (const d of docs) {
      if (d.kind !== "draft") continue;
      const dtoks = new Set(tokens(d.lines.join(" ")));
      let recipient = null;
      for (const ln of d.lines.slice(0, 8)) { const m = ln.match(/^\s*(?:hi|hello|dear|hey)\s+(\w+)/i); if (m) recipient = m[1].toLowerCase(); }
      if (![...dtoks].some((w) => topic.has(w)) && !inter(dtoks, people).size && !people.has(recipient)) continue;
      const gaps = [], used = new Set(), lines = d.lines;
      lines.forEach((ln, i) => {
        const s = ln.trim();
        if (!s || (i === 0 && s.toLowerCase().startsWith("draft"))) return;
        const nxt = (lines.slice(i + 1).map((x) => x.trim()).find((x) => x) || "");
        const emptyHeading = s.endsWith(":") && (!nxt || nxt.endsWith(":") || nxt === "-" || nxt === "*");
        if (!(INCOMPLETE_RX.test(s) || emptyHeading) || /^(hi|hello|dear|hey)\b/i.test(s)) return;
        if (s === "-" || s === "*") return;
        const label = strip(s.replace(/\[?\btodo\b[^\]]*\]?/gi, ""), " :[]-");
        const wantRisk = s.toLowerCase().trimEnd().endsWith("because") || label.toLowerCase().startsWith("risk");
        const wantMoney = /budget|number|cost|spend|price|£|\$|€/i.test(label);
        const wantAsk = label.toLowerCase().startsWith("ask");
        const q = new Map(tokens(label).filter((w) => !GENERIC.has(w) && !/^\d/.test(w) && !MONTHS_AND_DAYS.has(w) &&
          (!wantRisk || !SUBJECT_STOP.has(w))).map((w) => [w, 1.0]));
        const scored = [];
        for (const f of pool) {
          if (used.has(f.id)) continue;
          if (wantRisk && !f.tags.has("risk")) continue;
          if (wantMoney && !f.money.length) continue;
          let sc = q.size ? ix.bm25(q, f) : 0.0;
          if (wantRisk) sc += 1.0 + 0.5 * ix.bm25(topic, f);
          if (wantAsk && /\bneeds?\b.*\bsign[ -]?off\b|\bapproval\b/i.test(f.text)) sc += 2.0;
          if (sc > 0) scored.push([sc, f]);
        }
        let best = null, bestS = 0.0;
        if (scored.length) {
          const top = Math.max(...scored.map(([sc]) => sc));
          const good = scored.filter(([sc]) => sc >= (wantMoney ? 0.6 : 0.85) * top);
          [bestS, best] = maxBy(good, (x) => (wantMoney ? [x[1].date, x[0]] : [x[0], x[1].date]));
        }
        if (best && bestS > 1.0) {
          used.add(best.id);
          gaps.push({ line: s, line_no: i + 1, suggestion: item(best, { why: whyText(best, matched(q, best), "the closest match in your other notes"), confidence: "medium" }) });
        }
      });
      if (gaps.length) {
        out.push({ text: `“${d.title}” is unfinished: ${plural(gaps.length, "gap")} your notes may fill.`,
          headline: `Draft from ${fmtDate(d.date)}` + (recipient ? ` to ${roster.name(recipient)}` : ""),
          source: { path: d.path, file: d.display, title: d.title, kind: d.kind, line: 1, date: isoDate(d.date),
            date_label: fmtDate(d.date), date_guessed: d.dateSource.startsWith("file time") },
          gaps, why: "It's in your drafts and has empty or half-finished lines.", flags: ["unfinished"],
          confidence: "medium", more_sources: [], recipient: recipient ? roster.name(recipient) : null });
      }
    }
    return out;
  }

  function talkingPoints(sections, roster, people) {
    const byId = Object.fromEntries(sections.map((s) => [s.id, s]));
    const acts = (byId.actions || {}).items || [];
    const mine = acts.filter((it) => it.owner === "You" && it.flags.some((fl) => fl.startsWith("overdue") || fl.startsWith("written down")))
      .map((it) => ({ text: `Close the loop: “${it.text}”`, source: it.source,
        why: `${cap1(it.headline.split(/:(.*)/s)[1].trim())}, and nothing says it's done.` }));
    const changed = ((byId.changed || {}).items || []).map((it) => ({ text: `Confirm what's current: ${it.headline.replace("Changed: ", "")}`,
      source: it.source, why: "Your notes disagree with each other." }));
    const theirs = acts.filter((it) => !["You", "unassigned"].includes(it.owner) && people.has((it.owner || "").toLowerCase()))
      .map((it) => ({ text: `Ask ${it.owner}: “${it.text}”`, source: it.source, why: "It's theirs and still open in your notes." }));
    const qs = ((byId.questions || {}).items || []).map((it) => ({ text: `Get an answer: “${it.text}”`, source: it.source, why: it.headline + "." }));
    const drafts = ((byId.drafts || {}).items || []).filter((it) => it.recipient && people.has(it.recipient.toLowerCase()))
      .map((it) => ({ text: `Finish your update to ${it.recipient}: your notes can fill ${plural(it.gaps.length, "gap")}`, source: it.source, why: "It's still a draft." }));
    const pts = [...mine.slice(0, 2), ...changed.slice(0, 2), ...theirs.slice(0, 1), ...drafts.slice(0, 1), ...qs.slice(0, 1),
      ...mine.slice(2, 3), ...changed.slice(2, 3), ...theirs.slice(1, 2)];
    const seen = new Set(), out = [];
    for (const p of pts) if (!seen.has(p.text)) { seen.add(p.text); out.push(p); }
    return out.slice(0, 6);
  }

  // ------------------------------------------------------------------ questions
  const MY_ACTIONS_RX = /\b(i owe|owe|waiting on me|my (?:actions|todos?|to-?dos|tasks)|what do i (?:need|have) to do|on my plate|did i promise|i promised|i forgot|forgetting)\b/i;
  const CHANGED_RX = /\bwhat(?:'s| has| have)? changed\b|\bout of date\b|\bcontradict/i;
  const Q_WORDS = /\b(what|whats|when|who|whom|where|why|how|did|do|does|we|i|the|is|are|was|were|about|tell|me|find|show|any|anything|there|regarding|re|handling|handles|handle|doing|happening|status|latest|current|currently|going|working|looking|responsible|dealing|sorting|managing|owns|owner|mean|means|happened|remind|recall|again|our|my|on|with|for|of)\b/gi;

  function askGaps(context) {
    const out = [];
    if ((context.switched_off || []).length) out.push({ text: `Not searched: ${plural(context.switched_off.length, "file")} you switched off.`, kind: "scope" });
    if ((context.unreadable || []).length) out.push({ text: `Not searched: ${plural(context.unreadable.length, "image")} I can't read yet (${context.unreadable.slice(0, 2).join(", ")}).`, kind: "unreadable" });
    return out;
  }

  function ask(docs, question, today, context) {
    const roster = buildRoster(docs), frags = buildFrags(docs, roster), ix = new Index(frags, roster);
    const q = question.trim();
    if (!q) return { status: "empty" };
    if (MY_ACTIONS_RX.test(q)) {
      const threads = sortBy(buildThreads(ix, ["action", "question", "done"])
        .filter((t) => t.kind === "action" && threadStatus(t) === "open" && threadOwner(t) === "you"), (t) => [t.first.date]);
      const items = threads.slice(0, 8).map((t) => {
        const due = threadDue(t), flags = [`open ${plural(days(t.first.date, today), "day")}`];
        if (due !== null && due < today) flags.unshift(`overdue ${plural(days(due, today), "day")}`);
        if (t.frags.length > 1) flags.push(`written down ${t.frags.length} times`);
        return item(t.first, { why: whyText(t.first, null, t.frags.length > 1 ? `I linked ${t.frags.length} notes about the same thing` : ""),
          flags, extraSources: t.frags, headline: `Since ${fmtDate(t.first.date)}` });
      });
      return { status: items.length ? "found" : "not_found", kind: "my_actions",
        summary: items.length ? `${plural(threads.length, "thing")} you said you'd do that nothing in your notes marks as done. Oldest first:`
          : "I couldn't find anything you've promised that's still open.", items, gaps: askGaps(context) };
    }
    if (CHANGED_RX.test(q)) {
      const items = findChanges(ix).slice(0, 8).map((c) => ({ text: c.new.text, headline: `Changed: ${c.reason}`,
        before: { text: c.old.text, source: src(c.old) }, source: src(c.new), more_sources: [],
        why: "Two notes about the same thing disagree; newest shown first.",
        flags: ["changed"].concat(c.tentative ? ["tentative"] : []), confidence: "medium" }));
      return { status: items.length ? "found" : "not_found", kind: "changes",
        summary: items.length ? "Things your notes say differently over time, newest first:" : "I didn't find notes that contradict each other.",
        items, gaps: askGaps(context) };
    }
    const period = findPeriod(q, today);
    const qx = period ? q.slice(0, period[3][0]) + " " + q.slice(period[3][1]) : q;
    const inPeriod = period ? (f) => period[0] <= f.date && f.date <= period[1] : () => true;
    const plabel = period ? `${period[2]} (${fmtDate(period[0])}` + (period[1] !== period[0] ? ` to ${fmtDate(period[1])})` : ")") : "";
    let intent = /\b(decid\w*|decision\w*|agree\w*|go with|choose|chose)\b/i.test(qx) ? "decision"
      : /\bwhen\b|\bdate\b|\bdeadline\b/i.test(qx) ? "when"
      : /\b(how much|budget|cost|costs|price|pricing|spend)\b|[£$€]/i.test(qx) ? "amount"
      : /\bwho\b/i.test(qx) ? "who"
      : /\b(link|article|url|saved|bookmark)\b/i.test(qx) ? "link" : "";
    let content = qx.replace(Q_WORDS, " ");
    if (intent === "decision") content = content.replace(/\b(decid\w*|decision\w*|agree\w*|go with|choose|chose)\b/gi, " ");
    let only = intent === "decision" ? "decision" : null;
    if (period) {
      for (const [kind, rx] of KIND_WORDS) {
        if (rx.test(content)) { only = only || kind; content = content.replace(new RegExp(rx.source, "gi"), " "); }
      }
    }
    const words = (content.match(/[A-Za-z0-9£$€']+/g) || []).filter((w) => tokens(w).length && !GENERIC.has(tokens(w)[0]));
    const specific = tokens(content).filter((w) => !GENERIC.has(w));
    if (period && !specific.length) return periodOverview(frags, period, plabel, context, only);
    let qt = specific.length ? specific : tokens(content);
    const shown = new Map();
    for (const w of words) { const lw = w.toLowerCase(); shown.set(tokens(w)[0], lw.endsWith("'s") ? lw.slice(0, -2) : lw); }
    const sh = (w) => shown.get(w) || w;
    const query = new Map(), corrections = [];
    for (const w of qt) {
      const c = ix.df.get(w) ? null : closest(w, ix.df);
      if (c && !query.has(c) && !qt.includes(c)) { corrections.push([sh(w), c]); shown.set(c, c); query.set(c, 1.0); }
      else query.set(w, 1.0);
    }
    qt = [...query.keys()];
    const note = corrections.length ? "I read " + corrections.map(([a, b]) => `“${a}” as “${b}”`).join(", ") + ". " : "";
    if (!intent && (query.has("budget") || query.has("pricing"))) intent = "amount";
    const scored = [];
    for (const f of frags) {
      if (!inPeriod(f)) continue;
      let s = ix.bm25(query, f);
      if (s <= 0) continue;
      if (intent === "decision" && f.tags.has("decision")) s *= 1.6;
      if (intent === "when" && f.dates.length) s *= 1.3;
      if (intent === "amount" && f.money.length) s *= 1.5;
      if (intent === "link" && f.tags.has("link")) s *= 1.6;
      if (intent === "who" && (f.owner || f.people.size)) s *= 1.2;
      if (intent !== "link" && f.tags.has("link")) s *= 0.6;
      if (f.doc.kind === "draft") s *= 0.5;
      if (/\btodo\b|\[\s*\]\s*$|\btbd\b/i.test(f.text)) s *= 0.4;
      s *= 1 + 0.15 * Math.max(0.0, 1 - days(f.date, today) / 90);
      scored.push([s, f]);
    }
    const sortedScored = sortBy(scored, (x) => [-x[0]]);
    const totalW = sum([...query.keys()].map((w) => ix.weight(w))) || 1;
    const gaps = askGaps(context);
    const missing = [...query.keys()].filter((w) => !ix.df.get(w));
    const missingShare = sum(missing.map((w) => ix.weight(w))) / totalW;
    if (!sortedScored.length) {
      const files = new Set(frags.map((f) => f.doc.path)).size;
      const w = qt.slice(0, 4).map((x) => `“${sh(x)}”`).join(", ") || "that";
      if (period) return { status: "not_found", summary: note + `I couldn't find anything about ${w} in notes dated ${plabel}.`, items: [], gaps, query_words: qt };
      return { status: "not_found", summary: note + `I couldn't find anything about ${w} in the ${plural(files, "file")} you've let me see.`, items: [], gaps, query_words: qt };
    }
    const [topS, top] = sortedScored[0];
    const coverage = sum([...query.keys()].filter((w) => top.toks.includes(w)).map((w) => ix.weight(w))) / totalW;
    const knownW = sum([...query.keys()].filter((w) => !missing.includes(w)).map((w) => ix.weight(w))) || 1;
    const knownCov = sum([...query.keys()].filter((w) => top.toks.includes(w)).map((w) => ix.weight(w))) / knownW;
    const mt = (f) => matched(query, f).map(sh);
    if (missing.length && (missingShare >= 0.5 || (missingShare >= 0.3 && knownCov < 0.8))) {
      return { status: "not_found",
        summary: note + `I couldn't find anything about ${missing.map((w) => `“${sh(w)}”`).join(", ")} in your notes, so I can't answer that. These lines share some words with your question but don't answer it:`,
        items: sortedScored.slice(0, 3).map(([, f]) => item(f, { why: whyText(f, mt(f)), confidence: "low" })), gaps, query_words: qt };
    }
    if (coverage < 0.34 && !(missing.length && knownCov >= 0.8)) {
      return { status: "unsure", summary: note + "I'm not sure. Nothing in your notes clearly answers that. The closest lines only partly match:",
        items: sortedScored.slice(0, 3).map(([, f]) => item(f, { why: whyText(f, mt(f)), confidence: "low" })), gaps, query_words: qt };
    }
    const keep = sortedScored.filter(([s]) => s >= 0.45 * topS).slice(0, 10).map(([, f]) => f);
    const groups = [];
    for (const f of keep) {
      const grp = groups.find((gr) => Math.max(...gr.map((h) => ix.sim(f, h))) >= 0.3);
      if (grp) grp.push(f); else groups.push([f]);
    }
    let main = sortBy(groups[0].filter((f) => !f.tags.has("link") || intent === "link"), (f) => [f.date, f.id]);
    if (!main.length) main = groups[0];
    let latest = main[main.length - 1];
    if (intent === "decision") {
      const decs = sortedScored.filter(([, f]) => f.tags.has("decision"));
      if (decs.length) {
        const bestD = decs[0][0];
        const close = decs.filter(([s]) => s >= 0.5 * bestD).map(([, f]) => f);
        latest = maxBy(close, (f) => [/^\s*decision\b/i.test(f.text), f.date, f.id]);
        const m = new Map(main.map((f) => [f.id, f]));
        for (const x of close) if (x !== latest) m.set(x.id, x);
        main = sortBy([...m.values()], (f) => [f.date, f.id]);
      }
    }
    const qset = new Set(query.keys());
    const hasMoney = /[£$€]|\d+k\b/i.test(q), hasDate = findDates(q, today).length > 0;
    const changeFits = (c) => {
      if (!inter(c.subject, qset).size || !c.members.some((m) => keep.includes(m))) return false;
      if (c.kind === "money") return intent === "amount" || hasMoney;
      if (c.kind === "date") return intent === "when" || hasDate || [...c.subject].some((w) => !ix.ent.has(w) && qset.has(w));
      return true;
    };
    const changes = findChanges(ix).filter(changeFits);
    if (changes.length) {
      const c = changes[0];
      latest = c.new;
      const m = new Map(main.map((f) => [f.id, f])); m.set(c.old.id, c.old);
      main = sortBy([...m.values()], (f) => [f.date, f.id]);
    }
    const conf = coverage >= 0.66 ? "high" : "medium";
    const items = [item(latest, { why: whyText(latest, mt(latest)), headline: "Most recent answer in your notes", confidence: conf,
      flags: latest.tags.has("tentative") ? ["not final"] : [] })];
    const history = main.filter((f) => f !== latest && f.date <= latest.date);
    for (const f of history.slice(-4).reverse()) items.push(item(f, { why: whyText(f, mt(f)), headline: "Earlier", confidence: "medium" }));
    const used = new Set([latest, ...history]);
    const related = groups.flat().filter((f) => !used.has(f)).slice(0, 3);
    for (const f of related) items.push(item(f, { why: whyText(f, mt(f)), headline: "Also related", confidence: "medium" }));
    let summary = "Here's what your notes say, newest first.";
    if (changes.length) {
      const c = changes[0];
      summary = `Heads up: this changed (${c.reason}). Your notes from ${fmtDate(c.old.date)} and ${fmtDate(c.new.date)} disagree; the newest is first.`;
      if (c.tentative) summary += " It isn't final yet.";
    }
    if (missing.length) summary += ` (Nothing in your notes mentions ${missing.map((w) => `“${sh(w)}”`).join(", ")}.)`;
    if (period) summary += ` Only notes dated ${plabel}.`;
    return { status: "found", summary: note + summary, items, gaps, query_words: qt, confidence: conf };
  }

  // ---- spelling tolerance and time windows (as in brain.py) ----
  function editDistance(a, b, limit = 2) {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev2 = [], prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i].concat(new Array(b.length).fill(0));
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
      }
      prev2 = prev; prev = cur;
    }
    return prev[prev.length - 1];
  }
  function closest(word, vocab, minLen = 5) {
    if (word.length < minLen || !/^[a-z]+$/i.test(word)) return null;
    const limit = word.length < 7 ? 1 : 2;
    let best = null;
    for (const [v, n] of vocab) {
      if (!/^[a-z]+$/i.test(v) || v[0] !== word[0] || Math.abs(v.length - word.length) > limit) continue;
      const d = editDistance(word, v, limit);
      if (d <= limit) { const key = [d, -n, v]; if (!best || cmpKey(key, best[0]) < 0) best = [key, v]; }
    }
    return best ? best[1] : null;
  }
  const DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const PERIOD_RX = new RegExp(`\\b(today|yesterday|this week|last week|this month|last month|(?:in the |over the )?(?:past|last) (\\d{1,3}) days|since (${WD})|in (${MON}))\\b`, "i");
  function findPeriod(q, today) {
    const m = q.match(PERIOD_RX);
    if (!m) return null;
    const p = m[1].toLowerCase();
    let a, b, label;
    if (p === "today") { a = b = today; label = "today"; }
    else if (p === "yesterday") { a = b = today - 1; label = "yesterday"; }
    else if (p === "this week") { a = today - weekday(today); b = today; label = "this week"; }
    else if (p === "last week") { a = today - (weekday(today) + 7); b = a + 6; label = "last week"; }
    else if (p === "this month") { const [y, mo] = ymd(today); a = dnum(y, mo, 1); b = today; label = "this month"; }
    else if (p === "last month") { const [y, mo] = ymd(today); b = dnum(y, mo, 1) - 1; const [y2, m2] = ymd(b); a = dnum(y2, m2, 1); label = "last month"; }
    else if (m[2]) { const n = +m[2]; a = today - n; b = today; label = `in the last ${n} days`; }
    else if (m[3]) { const wd = WEEKDAYS[m[3].toLowerCase()]; a = today - mod(weekday(today) - wd, 7); b = today; label = `since ${DAY_FULL[weekday(a)]}`; }
    else { const mon = MONTHS[m[4].toLowerCase()]; const [y, tm] = ymd(today); const yy = mon <= tm ? y : y - 1; a = dnum(yy, mon, 1); b = lastDay(yy, mon); label = `in ${MONTH_FULL[mon - 1]}`; }
    return [a, b, label, [m.index, m.index + m[0].length]];
  }
  const KIND_WORDS = [["action", /\b(actions?|to-?dos?|tasks?)\b/i], ["risk", /\b(risks?|problems?|issues?|blockers?)\b/i],
    ["question", /\b(open questions?|questions?)\b/i]];
  const KIND_PLURAL = { decision: "Decisions", action: "Actions", risk: "Risks", question: "Open questions" };
  function kindLabel(f) {
    for (const [tg, label] of [["decision", "Decision"], ["done", "Done"], ["action", "Action"], ["risk", "Risk"], ["question", "Open question"]]) {
      if (f.tags.has(tg)) return label;
    }
    return "Note";
  }
  function periodOverview(frags, period, plabel, context, only) {
    const [a, b] = period;
    const inside = sortBy(frags.filter((f) => a <= f.date && f.date <= b && !f.tags.has("link") && (only == null || f.tags.has(only))),
      (f) => [-f.date, ![...f.tags].some((t) => t !== "tentative"), f.id]);
    const items = inside.slice(0, 12).map((f) => item(f, { why: whyText(f), headline: `${fmtDate(f.date)} · ${kindLabel(f)}`,
      flags: f.tags.has("tentative") ? ["not final"] : [], confidence: "high" }));
    const guessed = [...new Set(inside.filter((f) => f.dateGuessed).map((f) => f.doc.display))].sort();
    const gaps = askGaps(context);
    if (guessed.length) gaps.push({ text: `No dates inside ${guessed.join(", ")}, so they're placed by when the file was last changed.`, kind: "dates" });
    const what = only ? KIND_PLURAL[only].toLowerCase() : "anything";
    if (!items.length) return { status: "not_found", kind: "period", items: [], gaps, summary: `I found no ${what} in your notes dated ${plabel}.` };
    const more = inside.length > 12 ? ` Showing the newest 12 of ${inside.length}.` : "";
    const lead = only ? `${KIND_PLURAL[only]} your notes recorded` : "Here's what your notes recorded";
    return { status: "found", kind: "period", items, gaps, summary: `${lead} ${plabel}, newest first.${more}` };
  }

  // ------------------------------------------------------------------ chat
  const HELLO_RX = /^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|thanks|thank you|cheers)\b[\s!.,]*$/i;
  const HELP_RX = /^\s*(help|\?|what can you do|what do you do|how do (i|you) (use|work)|commands|what can i ask)\b/i;
  const MEETING_RX = /\b(prep(are)?( me)?( for)?|brief( me)?( for| on)?|get ready|ready for|next meeting|my meeting|meeting with|before (my|the) (meeting|1:1|call|steering))\b/i;
  const ABOUT_RX = /\b(?:who is|who's|whos|what do i know about|tell me about|anything (?:on|about)|catch me up on|update me on|update on|status of|what'?s (?:going on|happening|the latest) (?:with|on)|summari[sz]e|everything (?:on|about)|remind me about)\s+(.+?)[?.!]*$/i;
  const CHAT_SUGGESTIONS = ["Prepare me for my next meeting", "What do I owe people?", "What has changed?",
    "Catch me up on data residency", "Tell me about Dana", "When is the launch?"];
  const allEvents = (docs) => docs.flatMap((d) => d.events);

  function matchEvent(docs, msg, today, roster) {
    const evs = allEvents(docs);
    if (!evs.length) return null;
    const upcoming = sortBy(evs.filter((e) => e.date >= today), (e) => [startIso(e.start)]);
    if (/\bnext (meeting|call)\b|\bmy next\b/i.test(msg) && upcoming.length) return upcoming[0];
    const mt = new Set(tokens(msg));
    const names = new Set([...roster.full.keys()].filter((f) => new RegExp(`\\b${f}\\b`, "i").test(msg)));
    const oneToOne = /\b1\s*[:\-]\s*1\b|\bone[ -]?(on|to)[ -]?one\b/i.test(msg);
    let best = null, bestS = 0.0;
    for (const e of evs) {
      const others = e.attendees.filter((a) => a !== e.me);
      const firsts = new Set(others.map((a) => a.split(/\s+/)[0].toLowerCase()));
      const tt = new Set(tokens(e.title || "").filter((w) => !GENERIC.has(w)));
      let s = 2.0 * inter(mt, tt).size + 1.5 * inter(names, firsts).size;
      if (oneToOne && others.length === 1 && inter(names, firsts).size) s += 1.5;
      if (s <= 0) continue;
      s += e.date >= today ? 0.5 : 0;
      s -= 0.002 * Math.abs(e.date - today);
      if (s > bestS) { best = e; bestS = s; }
    }
    return best;
  }
  const synthetic = (title, attendees, today, label) => ({ id: "chat", title, attendees, me: null, description: "",
    date: today, start: { date: today, h: 23, mi: 59, s: 0 }, date_label: label });
  const asAnswer = (r) => { const o = Object.assign({}, r); o.answer_kind = o.kind || "question"; delete o.kind; return Object.assign({ kind: "answer" }, o); };

  function fixNames(msg, roster, docs) {
    const vocab = new Set(tokens(docs.filter((d) => d.kind !== "calendar").flatMap((d) => d.lines).join(" ")));
    const names = new Map([...roster.full.keys()].map((f) => [f, 1]));
    const fixes = [];
    const out = msg.replace(/[A-Za-z]+/g, (w) => {
      const lw = w.toLowerCase();
      if (lw.length < 4 || names.has(lw) || STOP.has(lw) || GENERIC.has(lw) || vocab.has(lw) || vocab.has(stem(lw))) return w;
      const c = closest(lw, names, 4);
      if (!c) return w;
      fixes.push([w, roster.name(c)]);
      return roster.name(c);
    });
    return [out, fixes];
  }

  function chat(docs, message, today, context) {
    const msg0 = (message || "").trim().slice(0, 500);
    if (!msg0) return { kind: "text", text: "Ask me anything about the notes you've allowed.", suggestions: CHAT_SUGGESTIONS };
    const roster = buildRoster(docs);
    const [msg, fixes] = fixNames(msg0, roster, docs);
    const r = chatInner(docs, msg, today, context, roster);
    if (fixes.length) {
      const note = "I read " + fixes.map(([a, b]) => `“${a}” as ${b}`).join(", ") + ". ";
      const key = r.kind === "answer" ? "summary" : "text";
      r[key] = note + (r[key] || "");
    }
    return r;
  }

  function chatInner(docs, msg, today, context, roster) {
    const files = new Set(docs.map((d) => d.path)).size;
    if (HELLO_RX.test(msg)) {
      return { kind: "text", suggestions: CHAT_SUGGESTIONS,
        text: `Hi! I can see ${plural(files, "file")} you've allowed. I only read them when you ask, and I keep nothing afterwards. What would you like to know?` };
    }
    if (HELP_RX.test(msg)) {
      return { kind: "help", suggestions: CHAT_SUGGESTIONS, text: "Here's what you can ask me:", lines: [
        "Prepare for a meeting: “prepare me for my 1:1 with Priya”, “brief me for steering”, “prepare me for my next meeting”.",
        "Catch up on a person or topic: “tell me about Dana”, “catch me up on data residency”.",
        "Ask a question: “when is the launch?”, “what did we decide about the vendor?”.",
        "Find what you've forgotten: “what do I owe people?”, “what has changed?”.",
        "Every answer quotes your notes with the file and line. If something isn't in your notes, I'll say so instead of guessing."] };
    }
    if (MEETING_RX.test(msg)) {
      const ev = matchEvent(docs, msg, today, roster);
      if (ev) {
        const b = brief(docs, ev, today, context);
        return { kind: "brief", brief: b, text: `Here's your brief for “${ev.title}” (${b.meeting.date_label}).` };
      }
      const upcoming = sortBy(allEvents(docs).filter((e) => e.date >= today), (e) => [startIso(e.start)]);
      if (upcoming.length) {
        return { kind: "text", text: "I couldn't tell which meeting you mean. These are coming up in your calendar:",
          suggestions: upcoming.slice(0, 5).map((e) => `Prepare me for ${e.title}`) };
      }
    }
    const m = msg.match(ABOUT_RX);
    let subject = m ? m[1].trim() : "";
    const bare = strip(msg, " ?.!").toLowerCase();
    if (!subject && roster.has(bare)) subject = bare;
    if (subject) {
      subject = subject.replace(/^(the|our|my)\s+/i, "");
      const ws = subject.split(/\s+/).filter(Boolean);
      const first = ws.length ? ws[0].toLowerCase().replace(/'s$/, "") : "";
      if (roster.has(first) && ws.length <= 2) {
        const full = roster.full.get(first);
        const b = brief(docs, synthetic(`Catch-up: ${full}`, [full], today, "Everything your notes say, as of today"), today, context);
        if (b.stats.lines_used) return { kind: "brief", brief: b, text: `Here's what your notes say about ${full}.` };
        return asAnswer(ask(docs, subject, today, context));
      }
      if (tokens(subject).some((w) => !GENERIC.has(w))) {
        const b = brief(docs, synthetic(cap1(subject), [], today, "Everything your notes say, as of today"), today, context);
        if (b.sections.some((s) => s.id !== "gaps" && s.items.length)) return { kind: "brief", brief: b, text: `Here's what your notes say about ${subject}.` };
        return asAnswer(ask(docs, subject, today, context));
      }
    }
    return asAnswer(ask(docs, msg, today, context));
  }

  return { inventory, readAll, readDoc, listMeetings, meetingBrief, ask, chat, fromIso, isoDate, fmtDate,
    setYear: (y) => { CURRENT_YEAR = y; }, tokens, findDates };
})();
if (typeof window !== "undefined") window.SBEngine = SBEngine;
