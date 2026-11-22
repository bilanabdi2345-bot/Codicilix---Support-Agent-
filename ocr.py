"""
Read the text in screenshots and photos, on this computer, with Windows' own
built-in text reader (Windows.Media.Ocr).

This is the one place Second Brain starts another program. The privacy guard
normally refuses every program launch; it makes one narrow exception, checked on
every launch, for exactly the command line built here:

  * the program is Windows PowerShell from the Windows folder, with fixed options;
  * the script is tools/windows_ocr.ps1 from this app's own folder (read it: it
    only reads images and prints their text);
  * every other argument is an image inside a folder you allowed, that you
    haven't switched off.

"-ExecutionPolicy Bypass" applies to that one process only; it changes no setting
on your computer. Windows' text reader works offline and saves nothing. The text
comes back to this app over a pipe and is kept in memory for that one answer only.

On Mac or Linux, or if Windows can't read text, screenshots are simply listed as
"can't read" and everything else works the same.
"""
from __future__ import annotations

import os
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "tools", "windows_ocr.ps1")
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell",
                          "v1.0", "powershell.exe")
PREFIX = [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SCRIPT]
MAX_IMAGES = 25
TIMEOUT = 60
RS = "\x1e"
NAME = "Windows' built-in text reader"


def available() -> bool:
    return os.name == "nt" and os.path.isfile(POWERSHELL) and os.path.isfile(SCRIPT)


def command(paths: list[str]) -> list[str]:
    return PREFIX + [os.path.abspath(p) for p in paths]


# The command this thread is about to run. The guard compares the real launch with it
# character for character (on Windows, Python joins the list into one string first).
_pending = threading.local()


def command_ok(argv, image_ok) -> bool:
    """Is this launch exactly the command `command()` built, for images you've allowed?
    The privacy guard asks this before letting the program start."""
    want = getattr(_pending, "argv", None)
    if not want:
        return False
    same = argv == subprocess.list2cmdline(want) if isinstance(argv, str) else \
        isinstance(argv, (list, tuple)) and [str(a) for a in argv] == want
    head, rest = want[:len(PREFIX)], want[len(PREFIX):]
    return (same and head == PREFIX and 0 < len(rest) <= MAX_IMAGES
            and all(os.path.isabs(p) and image_ok(p) for p in rest))


def start(paths: list[str], **kw) -> subprocess.Popen:
    """Start the text reader for these images (the check-up uses this to show it's refused
    for anything outside your folders)."""
    argv = command(paths)
    _pending.argv = argv
    try:
        return subprocess.Popen(argv, **kw)
    finally:
        _pending.argv = None


def read_images(paths: list[str]) -> dict[str, list[str] | str]:
    """{path: lines of text} for each image, or {path: "why it couldn't be read"}."""
    out: dict[str, list[str] | str] = {}
    paths = list(paths)
    if not paths:
        return out
    if not available():
        return {p: "this computer has no text reader Second Brain can use" for p in paths}
    for start in range(0, len(paths), MAX_IMAGES):
        batch = paths[start:start + MAX_IMAGES]
        argv = command(batch)
        _pending.argv = argv
        try:
            # pipes only (input=b"" closes its input at once): the guard refuses opening even the null device to write
            run = subprocess.run(argv, capture_output=True, timeout=TIMEOUT, input=b"",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            out.update({p: "the text reader took too long" for p in batch})
            continue
        except Exception as e:     # includes the privacy guard refusing it
            out.update({p: f"the text reader couldn't start ({type(e).__name__})" for p in batch})
            continue
        finally:
            _pending.argv = None
        by_abs = {os.path.normcase(os.path.abspath(p)): p for p in batch}
        current = None
        # split on newlines only: str.splitlines() would also split on the separator itself
        for raw in run.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
            if raw.startswith(RS + "ERROR "):
                if current:
                    out[current] = raw[len(RS) + 6:].strip() or "the text reader couldn't read it"
                continue
            if raw.startswith(RS):
                current = by_abs.get(os.path.normcase(os.path.abspath(raw[1:].strip())))
                if current:
                    out[current] = []
                continue
            if current and isinstance(out.get(current), list):
                out[current].append(raw.rstrip())
        for p in batch:
            out.setdefault(p, "the text reader gave no answer")
            while isinstance(out[p], list) and out[p] and not out[p][-1].strip():
                out[p].pop()           # the last newline isn't a line of text
    return out

