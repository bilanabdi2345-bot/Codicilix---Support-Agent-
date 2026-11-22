#!/usr/bin/env python3
"""
Second Brain for Managers - a personal assistant for your scattered notes that
works only on this device and keeps nothing.

    python app.py                       # opens http://127.0.0.1:8765 in your browser
    python app.py --allow "D:/my notes"  # start with a folder already allowed
    python app.py --today 2026-11-22     # pretend it's another day (for demos)

Python 3.10+ standard library only. No installs, no internet, no accounts.
"""

import sys

sys.dont_write_bytecode = True  # not even Python's own cache files get written

import argparse  # noqa: E402
import os  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# What you've allowed the assistant to see. In memory only: when the app stops,
# it's gone. Nothing about your notes is ever stored.
STATE = {"roots": [], "off": set()}


def _scope_roots():
    return [os.path.normcase(os.path.abspath(r)) for r in STATE["roots"]]


def _is_allowed(path):
    return os.path.normcase(os.path.abspath(path)) not in STATE["off"]


def parse_args():
    p = argparse.ArgumentParser(description="Second Brain - on-device, keeps nothing.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--allow", action="append", default=[], help="folder of notes to allow at start-up")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    p.add_argument("--today", help="treat this date (YYYY-MM-DD) as today, e.g. for demos")
    p.add_argument("--no-sample", action="store_true",
                   help="start empty instead of with the bundled simulated notes")
    return p.parse_args()


ARGS = parse_args()

# ---- the privacy guard goes in first, before the app does anything else ----
import guard  # noqa: E402

_PROGRAM = [sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.join(HERE, "ui"),
            os.path.join(HERE, "__pycache__")] + [os.path.join(HERE, f) for f in os.listdir(HERE) if f.endswith(".py")]
guard.install(scope_roots=_scope_roots, is_allowed=_is_allowed, program_roots=_PROGRAM,
              browser_url=f"http://127.0.0.1:{ARGS.port}/")

import datetime as dt  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import brain  # noqa: E402
import sources  # noqa: E402

UI = os.path.join(HERE, "ui")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")


def today() -> dt.date:
    if ARGS.today:
        return dt.date.fromisoformat(ARGS.today)
    return dt.date.today()


def inventory():
    return sources.inventory(STATE["roots"], STATE["off"])


def context(files):
    return {"switched_off": [f["display"] for f in files if f["switched_off"]],
            "unreadable": [f["display"] for f in files if not f["readable"]]}


SAMPLE = os.path.join(HERE, "sample_notes")
SAMPLE_NAME = "Simulated notes"


def is_sample(root) -> bool:
    return os.path.normcase(os.path.abspath(root)) == os.path.normcase(SAMPLE)


def root_name(root) -> str:
    return SAMPLE_NAME if is_sample(root) else (os.path.basename(root.rstrip("\\/")) or root)


def display_of(path, files):
    k = os.path.normcase(os.path.abspath(path))
    for f in files:
        if f["key"] == k:
            return f["display"]
    return hide_paths(path)


def hide_paths(text: str) -> str:
    """Never show where the app or your home folder sits on disk (it can reveal your name)."""
    out = str(text)
    for real, shown in ((SAMPLE, SAMPLE_NAME), (HERE, "<app folder>"), (os.path.expanduser("~"), "~")):
        for variant in {real, os.path.normcase(real), real.replace("\\", "/")}:
            out = out.replace(variant, shown)
    return out


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def api_state(_body):
    files = inventory()
    roots = []
    for r in STATE["roots"]:
        sample = is_sample(r)
        roots.append({"path": r, "name": root_name(r), "sample": sample,
                      "cloud": None if sample else sources.cloud_sync_warning(r),
                      "files": sum(1 for f in files if f["root"] == r)})
    return {"roots": roots, "files": files, "today": today().isoformat(),
            "sample_path": SAMPLE, "guard": guard.installed(), "pid": os.getpid()}


def api_scope_add(body):
    path = os.path.abspath(os.path.expanduser(str(body.get("path", "")).strip().strip('"')))
    if not os.path.isdir(path):
        return {"error": f"That folder doesn't exist on this device: {path}"}
    if any(os.path.normcase(path) == os.path.normcase(r) for r in STATE["roots"]):
        return {"ok": True}
    STATE["roots"].append(path)
    return {"ok": True, "cloud": sources.cloud_sync_warning(path)}


def api_scope_remove(body):
    path = os.path.normcase(os.path.abspath(str(body.get("path", ""))))
    STATE["roots"] = [r for r in STATE["roots"] if os.path.normcase(os.path.abspath(r)) != path]
    STATE["off"] = {k for k in STATE["off"] if not k.startswith(path)}
    return {"ok": True}


def api_scope_toggle(body):
    key = os.path.normcase(os.path.abspath(str(body.get("path", ""))))
    if body.get("allowed"):
        STATE["off"].discard(key)
    else:
        STATE["off"].add(key)
    return {"ok": True}


def api_meetings(_body):
    files = inventory()
    docs = sources.read_all([f for f in files if f["kind"] == "calendar"])
    return {"meetings": brain.list_meetings(docs, today()),
            "has_calendar": any(f["kind"] == "calendar" and f["allowed"] for f in files)}


def api_brief(body):
    files = inventory()
    docs = sources.read_all(files)
    return brain.meeting_brief(docs, str(body.get("id", "")), today(), context(files))


def api_ask(body):
    files = inventory()
    docs = sources.read_all(files)
    return brain.ask(docs, str(body.get("q", ""))[:500], today(), context(files))


def api_chat(body):
    files = inventory()
    docs = sources.read_all(files)
    return brain.chat(docs, str(body.get("message", ""))[:500], today(), context(files))


def api_source(body):
    files = inventory()
    key = os.path.normcase(os.path.abspath(str(body.get("path", ""))))
    f = next((x for x in files if x["key"] == key), None)
    if not f:
        return {"error": "That file isn't in a folder you've allowed."}
    if not f["allowed"]:
        return {"error": "You've switched that file off, so I won't open it."}
    with open(f["path"], "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    n = max(1, int(body.get("line", 1) or 1))
    lo, hi = max(1, n - 8), min(len(lines), n + 8)
    return {"file": f["display"], "path": f["path"], "path_display": f"{root_name(f['root'])}/{f['display']}",
            "line": n, "total": len(lines), "lines": [{"n": i, "text": lines[i - 1]} for i in range(lo, hi + 1)]}


def api_ledger(_body):
    snap = guard.LEDGER.snapshot()
    files = inventory()
    for e in snap["events"]:
        if e["kind"] in ("read_outside", "read_switched_off"):
            e["detail"] = display_of(e["detail"], files)
        else:
            e["detail"] = hide_paths(e["detail"])
    return snap


def api_leaktest(_body):
    results = guard.leak_test(HERE)
    for r in results:
        r["how"] = hide_paths(r["how"])
    return {"results": results}


def api_forget(_body):
    STATE["roots"].clear()
    STATE["off"].clear()
    guard.LEDGER.reset()
    guard.LEDGER.add("forget", "You ended the session: allowed folders and this ledger were cleared from memory.")
    return {"ok": True}


ROUTES = {
    ("GET", "/api/state"): api_state, ("GET", "/api/meetings"): api_meetings,
    ("GET", "/api/ledger"): api_ledger, ("GET", "/api/source"): api_source,
    ("POST", "/api/scope/add"): api_scope_add, ("POST", "/api/scope/remove"): api_scope_remove,
    ("POST", "/api/scope/toggle"): api_scope_toggle, ("POST", "/api/brief"): api_brief,
    ("POST", "/api/ask"): api_ask, ("POST", "/api/chat"): api_chat,
    ("POST", "/api/leaktest"): api_leaktest, ("POST", "/api/forget"): api_forget,
}


def receipt_summary(r, files):
    read = sorted({display_of(p, files) for p in r["read"]})
    return {
        "files_read": read, "files_read_count": len(read),
        "outside_scope": sorted(set(r["read_other"])), "blocked": r["blocked"], "network": r["net"],
        "written": 0,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SecondBrain"
    sys_version = ""

    def log_message(self, fmt, *args):   # keep the console quiet; nothing is logged to disk
        pass

    def _headers(self, code, ctype, length):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store, max-age=0")   # your browser keeps no copy either
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Security-Policy", CSP)            # the page can only talk to this app
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _json(self, code, obj):
        data = json.dumps(obj, default=str).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _trusted(self):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False                     # blocks DNS-rebinding tricks from other websites
        return True

    def _handle(self, method):
        if not self._trusted():
            return self._json(403, {"error": "Only this device's browser, at this app's address, may ask."})
        url = urlsplit(self.path)
        if method == "GET" and url.path in STATIC:
            name, ctype = STATIC[url.path]
            with open(os.path.join(UI, name), "rb") as fh:
                data = fh.read()
            self._headers(200, ctype, len(data))
            return self.wfile.write(data)
        fn = ROUTES.get((method, url.path))
        if fn is None:
            return self._json(404, {"error": "not found"})
        # other web pages can't send this custom header without a CORS preflight we never approve
        if self.headers.get("X-Second-Brain") != "1":
            return self._json(403, {"error": "Requests must come from the Second Brain page."})
        body = {k: v[0] for k, v in parse_qs(url.query).items()}
        if method == "POST":
            n = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
            if n:
                try:
                    body.update(json.loads(self.rfile.read(n) or b"{}"))
                except ValueError:
                    return self._json(400, {"error": "bad request"})
        started = time.perf_counter()
        with guard.receipt() as r:
            try:
                result = fn(body)
            except guard.Blocked as e:
                result = {"error": str(e)}
        files = inventory() if r["read"] else []
        out = {"data": result, "receipt": receipt_summary(r, files),
               "ms": round((time.perf_counter() - started) * 1000)}
        self._json(200, out)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def main():
    # Start with the bundled simulated notes already loaded, unless told otherwise,
    # so the app can be shown to others without touching anyone's real folders.
    if not ARGS.allow and not ARGS.no_sample and os.path.isdir(SAMPLE):
        api_scope_add({"path": SAMPLE})
    for folder in ARGS.allow:
        api_scope_add({"path": folder})
    port = ARGS.port
    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"Couldn't find a free port near {ARGS.port}.")
    url = f"http://127.0.0.1:{port}/"
    if port != ARGS.port:
        guard._browser_url = url
    print("\n  Second Brain is running on this device only.")
    print(f"  Open {url} in your browser.  (Ctrl+C to stop - everything it saw is forgotten.)")
    print(f"  Privacy guard: on. Process id {os.getpid()}.\n")
    if not ARGS.no_browser:
        def _open():
            time.sleep(0.6)
            try:
                if os.name == "nt":
                    os.startfile(url)  # noqa: S606 - the one exception the guard allows
                else:
                    import webbrowser
                    webbrowser.open(url)
            except Exception as e:  # pragma: no cover
                print(f"  (Couldn't open the browser automatically: {e})")
        threading.Thread(target=_open, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\n  Stopped. Nothing was saved.")


if __name__ == "__main__":
    main()
