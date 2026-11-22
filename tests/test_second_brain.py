"""
Run from the second-brain folder:   python -B -m unittest discover -s tests -v

-B stops Python writing cache files, so even the tests leave nothing behind.
"""
import datetime as dt
import os
import socket
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import brain  # noqa: E402
import sources  # noqa: E402

SAMPLE = os.path.join(HERE, "sample_notes")
TODAY = dt.date(2026, 11, 22)


def load(off=()):
    files = sources.inventory([SAMPLE], {sources.norm_key(os.path.join(SAMPLE, p)) for p in off})
    # Files with no date inside are dated by their file timestamp, and a fresh git clone stamps
    # everything "now". Pin those dates so the tests give the same results on any day.
    for f in files:
        f["modified"] = "2026-11-21"
    ctx = {"switched_off": [f["display"] for f in files if f["switched_off"]],
           "unreadable": [f["display"] for f in files if not f["readable"]]}
    return sources.read_all(files), ctx


def section(brief, sid):
    return next((s for s in brief["sections"] if s["id"] == sid), None)


class BriefTests(unittest.TestCase):
    def test_steering_brief_surfaces_what_changed(self):
        docs, ctx = load()
        b = brain.meeting_brief(docs, "steering-1124@sample", TODAY, ctx)
        heads = [i["headline"] for i in section(b, "changed")["items"]]
        self.assertTrue(any("1 Dec" in h and "15 Jan" in h for h in heads), heads)    # launch moved
        self.assertTrue(any("£40k" in h and "£55k" in h for h in heads), heads)      # budget went up
        self.assertTrue(any("£52k" in h and "£44k" in h for h in heads), heads)      # Kestrel got cheaper
        self.assertTrue(any("freeze" in h for h in heads), heads)                    # hire frozen
        self.assertEqual(len(heads), 4, heads)

    def test_forgotten_promise_is_found_across_files(self):
        docs, ctx = load()
        b = brain.meeting_brief(docs, "one-one-priya-1123@sample", TODAY, ctx)
        acts = section(b, "actions")["items"]
        promise = next(i for i in acts if "tech lead" in i["text"])
        self.assertEqual(promise["owner"], "You")
        self.assertIn("written down 4 times", promise["flags"])
        self.assertTrue(any(f.startswith("overdue") for f in promise["flags"]))
        files = {promise["source"]["file"]} | {s["file"] for s in promise["more_sources"]}
        self.assertTrue({"quick/reminders.md", "quick/scratch.txt"} <= files, files)

    def test_draft_gap_filled_with_latest_figure(self):
        docs, ctx = load()
        b = brain.meeting_brief(docs, "steering-1124@sample", TODAY, ctx)
        draft = section(b, "drafts")["items"][0]
        budget_gap = next(g for g in draft["gaps"] if "Budget" in g["line"])
        self.assertIn("£55k", budget_gap["suggestion"]["text"])

    def test_brief_is_honest_about_what_it_could_not_read(self):
        docs, ctx = load(off=["quick/scratch.txt"])
        b = brain.meeting_brief(docs, "steering-1124@sample", TODAY, ctx)
        gaps = " ".join(g["text"] for g in section(b, "gaps")["items"])
        self.assertIn("whiteboard", gaps)          # the screenshot it can't read
        self.assertIn("switched off", gaps)        # the file the user excluded
        # and nothing from the switched-off file appears anywhere
        self.assertNotIn("scratch.txt", repr(b["sections"][:-1]))

    def test_every_item_cites_a_real_line(self):
        docs, ctx = load()
        b = brain.meeting_brief(docs, "steering-1124@sample", TODAY, ctx)
        for s in b["sections"]:
            for it in s["items"]:
                src = it.get("source")
                if not src or s.get("plain"):
                    continue
                with open(src["path"], encoding="utf-8") as fh:
                    line = fh.read().splitlines()[src["line"] - 1]
                self.assertTrue(it["text"][:12].strip("“” ") in line or it.get("gaps"), (it["text"], line))


class AskTests(unittest.TestCase):
    def ask(self, q):
        docs, ctx = load()
        return brain.ask(docs, q, TODAY, ctx)

    def test_launch_date_flags_the_change(self):
        r = self.ask("When is the launch?")
        self.assertEqual(r["status"], "found")
        self.assertIn("changed", r["summary"])
        self.assertIn("15 Jan", r["items"][0]["text"])
        self.assertIn("not final", r["items"][0]["flags"])

    def test_vendor_decision(self):
        r = self.ask("What did we decide about the vendor?")
        self.assertIn("Brightline", r["items"][0]["text"])

    def test_says_so_when_it_does_not_know(self):
        for q in ("What's Tom's phone number?", "what's the office wifi password"):
            r = self.ask(q)
            self.assertEqual(r["status"], "not_found", q)
            self.assertIn("couldn't find", r["summary"])

    def test_my_open_promises(self):
        r = self.ask("What do I owe people?")
        texts = " ".join(i["text"] for i in r["items"])
        self.assertIn("tech lead", texts)
        self.assertNotIn("security questionnaire", texts)   # that one is marked done


class ChatTests(unittest.TestCase):
    def chat(self, msg):
        docs, ctx = load()
        return brain.chat(docs, msg, TODAY, ctx)

    def test_meeting_requests_become_briefs(self):
        for msg, title in (("prepare me for my 1:1 with Priya", "1:1 Priya"),
                           ("brief me for steering", "Atlas steering group"),
                           ("prepare me for my next meeting", "1:1 Priya")):
            r = self.chat(msg)
            self.assertEqual(r["kind"], "brief", msg)
            self.assertEqual(r["brief"]["meeting"]["title"], title, msg)

    def test_unknown_meeting_offers_choices(self):
        r = self.chat("prepare me for the board meeting")
        self.assertEqual(r["kind"], "text")
        self.assertTrue(any("steering" in s for s in r["suggestions"]))

    def test_person_and_topic_catch_up(self):
        r = self.chat("tell me about Dana")
        self.assertEqual(r["kind"], "brief")
        self.assertIn("Dana", r["brief"]["meeting"]["title"])
        r = self.chat("catch me up on data residency")
        self.assertEqual(r["kind"], "brief")
        acts = next(s for s in r["brief"]["sections"] if s["id"] == "actions")["items"]
        self.assertIn("written down 4 times", acts[0]["flags"])

    def test_questions_and_honesty(self):
        r = self.chat("when is the launch?")
        self.assertEqual((r["kind"], r["status"]), ("answer", "found"))
        r = self.chat("tell me about the moon landing")
        self.assertEqual((r["kind"], r["status"]), ("answer", "not_found"))
        self.assertEqual(self.chat("what do I owe people?")["answer_kind"], "my_actions")

    def test_greeting_and_help(self):
        self.assertEqual(self.chat("hi")["kind"], "text")
        self.assertEqual(self.chat("help")["kind"], "help")


class FeatureTests(unittest.TestCase):
    def chat(self, msg):
        docs, ctx = load()
        return brain.chat(docs, msg, TODAY, ctx)

    def test_spreadsheet_action_list(self):
        docs, _ = load()
        sheet = next(d for d in docs if d.kind == "actions")
        self.assertIn("- [ ] Send Tom the welcome pack · me · by 2026-11-25", sheet.lines)
        b = brain.meeting_brief(docs, "tom-day1-1126@sample", TODAY, load()[1])
        acts = next(s for s in b["sections"] if s["id"] == "actions")["items"]
        pack = next(i for i in acts if "welcome pack" in i["text"])
        self.assertEqual(pack["owner"], "You")
        self.assertIn("due 25 Nov", pack["flags"])
        self.assertEqual(pack["source"]["line"], 2)      # line 2 of the spreadsheet itself

    def test_spelling_mistakes_are_forgiven(self):
        r = self.chat("what's the budjet?")
        self.assertTrue(r["summary"].startswith("I read “budjet” as “budget”"), r["summary"])
        self.assertIn("£55k", r["items"][0]["text"])
        self.assertEqual(self.chat("prepare me for my 1:1 with prya")["brief"]["meeting"]["title"], "1:1 Priya")
        # a real word in the notes is never "corrected" into a name ("data" is not "Dana")
        self.assertNotIn("I read", self.chat("catch me up on data residency")["text"])
        self.assertNotIn("I read", self.chat("what is the reading on the launch?").get("summary", ""))

    def test_time_questions(self):
        r = self.chat("what happened last week?")
        self.assertEqual(r["answer_kind"], "period")
        self.assertTrue(r["items"])
        for it in r["items"]:
            self.assertTrue("2026-11-09" <= it["source"]["date"] <= "2026-11-15", it["source"]["date"])
        r = self.chat("decisions in October")
        self.assertTrue(r["items"] and all("Decision" in it["headline"] for it in r["items"]))

    def test_mostly_unknown_question_is_refused(self):
        r = self.chat("What is the zorblax quantum flux reading?")
        self.assertEqual(r["status"], "not_found")


class FakeOllama:
    """A stand-in for Ollama on 127.0.0.1: lists one model and answers with cited test bullets."""
    from http.server import BaseHTTPRequestHandler as _B

    class Handler(_B):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            import json
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"models": [{"name": "test-stand-in:1b"}]})

        def do_POST(self):
            import json
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            FakeOllama.last = body
            self._send({"message": {"content": "- The launch moved to 15 Jan [2]\n- It was 1 Dec before [1][9]\n"
                                               "- Something with no source"}})


class YServerTests(unittest.TestCase):
    """The real server over HTTP: secret key, chat, local AI write-ups and the check-up."""

    @classmethod
    def setUpClass(cls):
        import json
        import threading
        from http.server import ThreadingHTTPServer
        argv = sys.argv
        sys.argv = ["app.py", "--token", "test-key", "--no-browser", "--today", "2026-11-22"]
        try:
            import app
        finally:
            sys.argv = argv
        import ai
        cls.app, cls.json = app, json
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama.Handler)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        ai.OLLAMA = f"http://127.0.0.1:{cls.fake.server_address[1]}"
        app.api_scope_add({"path": SAMPLE})
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        app.SERVER["address"] = cls.srv.server_address[:2]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.fake.shutdown()

    def call(self, method, path, body=None, key="test-key", host=None):
        import http.client
        port = self.srv.server_address[1]
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if key:
            headers["X-Second-Brain-Key"] = key
        data = None
        if body is not None:
            data = self.json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        out = (r.status, self.json.loads(r.read()))
        c.close()
        return out

    def test_only_the_window_with_the_key_is_answered(self):
        self.assertEqual(self.call("GET", "/api/state", key=None)[0], 403)
        self.assertEqual(self.call("GET", "/api/state", key="wrong")[0], 403)
        self.assertEqual(self.call("GET", "/api/state", host="evil.example")[0], 403)
        status, body = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["ai"]["available"])

    def test_chat_over_http_comes_with_a_receipt(self):
        status, body = self.call("POST", "/api/chat", {"message": "when is the launch?"})
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "found")
        self.assertGreater(body["receipt"]["files_read_count"], 0)
        self.assertEqual(body["receipt"]["written"], 0)
        self.assertEqual(body["receipt"]["outside_scope"], [])

    def test_local_ai_write_up_is_cited_and_local(self):
        items = [{"text": "Launch date 1 Dec confirmed.", "file": "a.md", "date": "27 Oct"},
                 {"text": "agreed: move launch to 15 Jan", "file": "b.md", "date": "10 Nov"}]
        status, body = self.call("POST", "/api/ai", {"request": "When is the launch?", "items": items})
        d = body["data"]
        self.assertEqual(d["model"], "test-stand-in:1b")
        self.assertEqual(d["points"][0]["cites"], [2])
        self.assertEqual(d["points"][1]["cites"], [1])
        self.assertEqual(d["points"][1]["bad_cites"], [9])      # a source that doesn't exist is dropped
        self.assertEqual(d["uncited"], 1)                      # and an unsourced point is flagged
        sent = FakeOllama.last
        self.assertEqual(sent["keep_alive"], 0)                # the model is told to forget straight away
        self.assertIn("[2] (10 Nov, b.md) agreed: move launch to 15 Jan", sent["messages"][1]["content"])

    def test_checkup_passes_every_check(self):
        status, body = self.call("POST", "/api/checkup", {})
        d = body["data"]
        failed = [c for c in d["checks"] if c["status"] != "pass"]
        self.assertEqual(failed, [])
        self.assertEqual(d["passed"], d["total"])


class ZGuardTests(unittest.TestCase):
    """Runs last: once the guard is installed it stays on for the whole process."""

    @classmethod
    def setUpClass(cls):
        import guard
        cls.guard = guard
        guard.install(scope_roots=lambda: [os.path.normcase(SAMPLE)], is_allowed=lambda p: True,
                      program_roots=[sys.prefix, sys.base_prefix, HERE])

    def test_network_off_device_is_refused(self):
        with self.assertRaises(self.guard.Blocked):
            socket.getaddrinfo("example.com", 443)
        s = socket.socket()
        try:
            with self.assertRaises(self.guard.Blocked):
                s.connect(("1.1.1.1", 443))
        finally:
            s.close()

    def test_loopback_is_allowed(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        c = socket.create_connection(srv.getsockname(), timeout=2)
        c.close()
        srv.close()

    def test_listening_on_the_network_is_refused(self):
        s = socket.socket()
        try:
            with self.assertRaises(self.guard.Blocked):
                s.bind(("0.0.0.0", 0))
        finally:
            s.close()

    def test_no_files_can_be_written(self):
        with self.assertRaises(self.guard.Blocked):
            open(os.path.join(HERE, "should-not-exist.txt"), "w")
        self.assertFalse(os.path.exists(os.path.join(HERE, "should-not-exist.txt")))

    def test_no_other_programs(self):
        import subprocess
        with self.assertRaises(self.guard.Blocked):
            subprocess.run(["cmd", "/c", "echo"] if os.name == "nt" else ["true"])

    def test_reads_are_receipted(self):
        with self.guard.receipt() as r:
            docs, _ = load()
        self.assertTrue(r["read"])
        self.assertTrue(all(p.startswith(os.path.normcase(SAMPLE)) for p in r["read"]))
        self.assertEqual(r["read_other"], [])

    def test_leak_test_blocks_everything(self):
        results = self.guard.leak_test(HERE)
        self.assertTrue(all(x["blocked"] for x in results), results)


if __name__ == "__main__":
    unittest.main()
