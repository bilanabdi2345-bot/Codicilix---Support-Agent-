"""
build_demo.py - bundle Second Brain into one shareable web page.

    python -B web/build_demo.py web/second-brain-demo.html

The page contains the same interface (ui/), the browser port of the engine
(web/engine.js), a stand-in for the server that works inside the page
(web/demo-backend.js) and the simulated notes from sample_notes/. It never
contains anything from your own folders: only sample_notes/ is bundled, and
only by its path inside that folder.

Pass --preview to also wrap it in a full HTML document for local testing.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.dont_write_bytecode = True

import sources  # noqa: E402

DEMO_TODAY = "2026-11-22"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sample_files():
    root = os.path.join(APP, "sample_notes")
    out = []
    for f in sources.inventory([root], set()):
        text = None
        if f["readable"]:
            text = read(f["path"])
        out.append({"display": f["display"], "modified": f["modified"], "size": f["size"], "text": text})
    return out


def script(code):
    return "<script>\n" + code.replace("</script", "<\\/script") + "\n</script>\n"


def build():
    index = read(os.path.join(APP, "ui", "index.html"))
    body = re.search(r"<body>(.*)</body>", index, re.S).group(1)
    body = re.sub(r'\s*<script src="/app\.js"></script>\s*', "\n", body)
    files = sample_files()
    data = ("window.SB_DEMO_TODAY = " + json.dumps(DEMO_TODAY) + ";\n"
            "window.SB_DEMO_FILES = " + json.dumps(files, ensure_ascii=False, indent=0) + ";")
    page = (
        "<title>Second Brain</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        "<style>\n" + read(os.path.join(APP, "ui", "style.css")) + "\n</style>\n"
        + body.strip() + "\n"
        + script(data)
        + script(read(os.path.join(HERE, "engine.js")))
        + script(read(os.path.join(HERE, "demo-backend.js")))
        + script(read(os.path.join(APP, "ui", "app.js")))
    )
    return page, files


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "second-brain-demo.html")
    page, files = build()
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {out} ({len(page) // 1024} KB, {len(files)} simulated files)")
    if "--preview" in sys.argv:
        prev = sys.argv[sys.argv.index("--preview") + 1]
        with open(prev, "w", encoding="utf-8") as f:
            f.write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                    "</head><body>\n" + page + "</body></html>\n")
        print(f"wrote preview {prev}")
