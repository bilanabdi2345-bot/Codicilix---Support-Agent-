# Second Brain for Managers

**Help from your own notes. Nothing leaves this device, and nothing is kept.**

A personal assistant for a manager whose notes are scattered across meeting notes, reminders, half-written updates, saved links, a calendar and screenshots. It runs on your own computer, works without the internet, and keeps no copy of anything it reads.

## The moment it fixes: walking into a meeting unprepared

You're about to meet someone, and everything you know about it is spread across five files and six weeks. Pick the meeting from your calendar, and in about 100 ms you get a brief that:

- **Recaps last time**: the decisions, actions and open points from your previous meeting with these people.
- **Flags what changed since it was agreed.** In the sample notes, the launch moved from 1 Dec to 15 Jan (not final yet), the budget went from £40k to £55k, the rejected vendor got cheaper after you turned it down on price, and an approved hire was frozen.
- **Finds promises you forgot.** "Raise Priya's tech-lead role with Helen" was promised on 13 Oct, written down 4 times in 4 different files, and is 22 days overdue.
- **Lists what's still unanswered**, such as data residency, chased 4 times since 20 Oct.
- **Finishes your half-written drafts from your own notes.** Your unsent update to Helen says `Budget: [TODO numbers]`, and the brief points to the £55k from your 10 Nov notes.
- **Gives talking points**: if you only read one thing, read this.
- **Says what it couldn't check**: a screenshot it can't read (and the note that mentions it), files you switched off, and files with no dates.

Every line it shows is **quoted from your notes, with the file, line and date**. Click any source and the original opens at that line. "Why this?" explains in plain words why it was included.

**Chat with your notes.** The app opens on a chat where you can ask in your own words:

- "Prepare me for my 1:1 with Priya", "brief me for steering" or "prepare me for my next meeting" gives you the full brief.
- "Tell me about Dana" or "catch me up on data residency" gives you everything your notes say about a person or topic.
- "When is the launch?", "What did we decide about the vendor?", "What do I owe people?" or "What has changed?" gives you a direct answer, quoted from your notes.
- When the answer isn't in your notes, it says so ("I couldn't find anything about 'phone'…") instead of guessing.

The conversation exists only in the open page. **New chat**, a refresh or **End session & forget** clears it, and the server keeps no history.

## Run it

You need Python 3.10 or newer. Nothing to install: it uses only Python's standard library.

```
git clone https://github.com/davidxu16/ai-assistant.git
cd ai-assistant
python app.py
```

Your browser opens at `http://127.0.0.1:8765` with the **simulated notes already loaded** (a fictional manager's notes, shown as "Simulated notes" with no folder path). Type in the chat, for example "prepare me for my next meeting", or open **Prepare for a meeting** and pick **Atlas steering group**.
(On Windows you can also double-click `Start Second Brain.bat`.)

Options: `--allow "D:\My notes"` starts with your own folder instead of the simulated notes, and `--no-sample` starts empty. `--today 2026-11-22` pins the date, so the sample meetings stay "upcoming" whenever you run it. `--port 8765` and `--no-browser` also work.

## Shareable web demo

`web/second-brain-demo.html` is the same app as a single web page that anyone can open from a link. It has the simulated notes built in and does all its work **inside the visitor's browser**: no server, nothing sent, nothing stored. Its **Proof** tab counts the page's network requests (0), and its leak test shows the browser refusing every attempt to send data elsewhere.

- `web/engine.js` is a line-by-line JavaScript port of `sources.py` and `brain.py`. It was checked against the Python engine on all 5 meeting briefs and 30 chat messages, with and without a file switched off, and gave identical results.
- `web/demo-backend.js` answers the interface's requests inside the page.
- Rebuild after changes with `python -B web/build_demo.py web/second-brain-demo.html`. Only `sample_notes/` is bundled, never your own folders.

## The one rule, and how it's upheld

| Promise | How it's enforced | How you can check |
|---|---|---|
| **Nothing it reads leaves the device** | `guard.py` installs a Python **audit hook** (PEP 578) before the app does anything else. The interpreter calls it *before* every socket connection, DNS lookup, UDP send and URL request, and it refuses anything that isn't this machine's loopback address. Once installed, an audit hook can't be removed. The server only listens on `127.0.0.1`, and binding to the network is refused too. | **Proof** tab → **Run the leak test**: the app tries a DNS lookup, a connection to 1.1.1.1, a web request, writing a file and starting a program, and all 5 are blocked. Then use your own OS tools: `Get-NetTCPConnection -OwningProcess <pid>` shows only 127.0.0.1. Or turn on flight mode: everything still works. |
| **It keeps no copy** | Each request reads the files fresh, answers, and drops everything. There's no index, database or cache. The guard **refuses every file write, rename and delete** in the process, and the app even turns off Python's own `.pyc` cache. API responses are sent `Cache-Control: no-store`, and the page uses no browser storage. | The **Proof** tab shows "0 files written". After running it, there's no new file anywhere, not even `__pycache__`. |
| **No helpers that could leak for it** | The guard refuses to start other programs. The only exception is opening your browser once, at the app's own address. | Leak test, attempt 5. |
| **Other websites can't ask it for your notes** | The API needs a custom header that cross-site pages can't send without a CORS approval it never gives, and it checks the `Host` header to defeat DNS rebinding. A strict Content-Security-Policy means the page itself can only talk to this app. | `curl http://127.0.0.1:8765/api/state` → refused. |
| **You choose what it sees, and can change your mind** | Add folders, switch off any file, remove folders, or **End session & forget**. A switched-off file is never opened, and the guard would flag it in red if it were. | Every answer has a **receipt**: the exact files the guard saw being read for that answer. |
| **Honest about the cloud** | If a folder you add is inside OneDrive, Dropbox, Google Drive or iCloud, it warns you that *the sync app* is already copying it off the device. | Add a folder inside OneDrive and the warning appears. |

## How it copes with messy notes

Real notes look like `marco STILL hasnt confirmed EU data residency!! chase` or `kestrel came back w/ 15% discount?? → 44k`. It handles:

- **Tagging each line** as an action, decision, question, risk or done item, using the forms people actually write: `[ ]`, `AI:`, `me:`, `Dana to…`, `chase`, `ask Helen`, `✅`, `DECISION:`, `agreed`, `TBC`, `??`. Negation counts, so "hasn't confirmed" is not a confirmation.
- **Dates in any form**: `13/10`, `27 Oct`, `Tue 6 Oct 2026`, `by Fri`, `end of month`, and per-line dates in phone notes ("12 Nov - corridor chat…"). Files with no date fall back to the file's timestamp, and it **says when it did that**.
- **Shorthand and synonyms**: `1:1`, `TL` = tech lead, `w/`, `convo`, `costs` ≈ `budget`, `go-live` ≈ `launch`, `hc` ≈ `headcount`.
- **Threads**: lines about the same thing are linked across files and weeks, so a promise repeated in a 1:1, a reminder and a scratch file reads as one item ("written down 4 times").
- **Changes**: a different number or date next to the *same subject word*, and about the same named thing (Kestrel's price is never compared with Brightline's), or a later line saying "on hold", "moved to", "revised" or "freeze" about an earlier decision.

It runs on careful heuristics and classic information retrieval (BM25), not a cloud model. That's what lets it run anywhere, instantly and offline. It also keeps it honest: it can only quote you, never invent.

## Judging criteria, mapped

| Criterion | Where to look |
|---|---|
| Insight & problem understanding | One real moment (meeting prep), built around the four failures in the brief: **capture** (finishes drafts), **find** (quotes with sources), **connect** (threads and changes across files), **trust** (the guard and receipts). |
| Creative use of AI & design | Not a chatbot over notes. It *proactively* finds forgotten promises, contradictions and unfinished drafts, and turns them into talking points. It copes with messy, fragmentary and out-of-date notes by design. |
| Working end to end | `python app.py` → sample notes → pick a meeting → brief. It works across **six kinds of content**: notes, reminders, drafts, calendar (.ics), saved links (.md/.url) and screenshots (acknowledged, not yet read). |
| Trust & explainability | Every item is a quote with file, line and date, plus "Why this?". It has confidence labels, "I couldn't find…" answers, and a "What I couldn't check" section on every brief. |
| Knowledge stays yours | The audit-hook guard, the leak test, per-answer receipts, OS-level checks, folder and file switches, "End session & forget", and the cloud-sync warning. |

## Honest limitations

- The heuristics are tuned for English work notes. They will miss things, which is why every item links to its source and the brief lists what it couldn't check.
- Screenshots aren't read yet. On-device OCR (for example, the OCR built into Windows) is the natural next step, and the brief already tells you when a screenshot might matter.
- Audit hooks guard this Python process. They are not a sandbox against malicious native code. That's why the app also tells you how to verify it with your OS's own tools.
- The browser is a separate program. The app limits it with `no-store`, a strict CSP and no browser storage, but your browser's own features (for example, sync or extensions) are yours to manage.
- An optional on-device LLM (for example, via Ollama on 127.0.0.1, which the guard already allows) could rephrase briefs. It's deliberately left out, so every word you see is traceable to your notes.

## Files

| File | What it does |
|---|---|
| `app.py` | Local web server (127.0.0.1 only). Installs the guard first, and keeps the list of allowed folders in memory only. |
| `guard.py` | The privacy guard (audit hooks), the in-memory ledger, per-request receipts and the leak test. |
| `sources.py` | Finds and reads allowed files: notes, calendar, links, drafts and reminders. No caching. |
| `brain.py` | Tagging, threads, change detection, the meeting brief, questions and the chat router. |
| `ui/` | The interface (HTML/CSS/JS, no external resources; light and dark themes). |
| `web/` | The shareable web demo: browser engine, in-page backend, build script and the built page. |
| `sample_notes/` | Fictional notes for a fictional manager. No real person's notes. |
| `tests/` | `python -B -m unittest discover -s tests -v` (21 tests: briefs, questions, chat and the guard). |
