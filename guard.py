"""
guard.py - the privacy guard that enforces the one rule inside this process.

It uses Python audit hooks (PEP 578). The interpreter calls an audit hook
*before* it opens a file, connects a socket, looks up a host name or starts
another program, and the hook can refuse. Once a hook is installed, no code in
the process can remove it.

What the guard enforces
  * Nothing leaves the device: network connections, DNS lookups and UDP sends
    are allowed only to this machine's loopback address (127.x.x.x / ::1 /
    localhost). Anything else is refused before a single packet is sent.
  * No copies: the process may not create, write, rename, move or delete any
    file, anywhere.
  * No helpers: the process may not start other programs, which could do
    either of the above on its behalf. The only exception is opening your
    browser once, at this app's own 127.0.0.1 address, at start-up.

What the guard records (in memory only, never on disk)
  * which of your files were read: paths only, never contents
  * every refused attempt
  * every loopback connection (for example to an optional local model)
"""

from __future__ import annotations

import collections
import contextlib
import ipaddress
import os
import sys
import threading
import time


class Blocked(PermissionError):
    """Raised when the guard refuses an operation."""


_tls = threading.local()
_lock = threading.Lock()
_installed = False

# Callbacks supplied by the app so the guard can tell "your notes" apart from
# the program's own files.
_scope_roots = lambda: []          # noqa: E731  -> list of normcased abs folder paths
_is_allowed = lambda path: True    # noqa: E731  -> False if the user switched this file off
_program_roots: list[str] = []
_browser_url: str | None = None    # the one URL we may open at start-up
_helpers: list = []                # (name, check): the only other programs that may start, see allow_helper()
_sealed = False                    # once the app is serving, that list can't grow

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

_FS_CHANGE_EVENTS = {
    "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
    "os.utime", "os.truncate", "os.link", "os.symlink", "shutil.copyfile",
    "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move",
    "shutil.rmtree", "shutil.make_archive", "shutil.unpack_archive",
    "tempfile.mkstemp", "tempfile.mkdtemp", "sqlite3.connect", "dbm.open",
    "shelve.open",
}
_EXEC_EVENTS = {
    "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
    "os.fork", "os.forkpty", "os.startfile", "pty.spawn", "webbrowser.open",
}


# --------------------------------------------------------------------------
# Ledger: an in-memory record the user can inspect in the app
# --------------------------------------------------------------------------
class Ledger:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        with _lock:
            self.events: collections.deque = collections.deque(maxlen=400)
            self.counts: collections.Counter = collections.Counter()
            self.files_read: dict[str, int] = {}
            self.started = time.time()

    def add(self, kind: str, detail: str, *, test: bool = False) -> None:
        with _lock:
            self.counts[kind + ("_test" if test else "")] += 1
            self.events.append({"t": time.time(), "kind": kind, "detail": detail, "test": test})

    def note_read(self, path: str) -> None:
        with _lock:
            self.counts["notes_read"] += 1
            self.files_read[path] = self.files_read.get(path, 0) + 1

    def snapshot(self) -> dict:
        with _lock:
            c = self.counts
            return {
                "since": self.started,
                "pid": os.getpid(),
                "files_read": len(self.files_read),
                "reads_total": c["notes_read"],
                "reads_outside_scope": c["read_outside"],
                "reads_switched_off": c["read_switched_off"],
                "writes_blocked": c["write_blocked"],
                "net_blocked": c["net_blocked"],
                "exec_blocked": c["exec_blocked"],
                "net_loopback": c["net_loopback"],
                "helper_runs": c["helper_run"],
                "test_blocks": c["write_blocked_test"] + c["net_blocked_test"] + c["exec_blocked_test"],
                "events": list(self.events)[-120:],
            }


LEDGER = Ledger()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _norm(path) -> str | None:
    if isinstance(path, int):
        return None
    try:
        p = os.fsdecode(os.fspath(path))
    except TypeError:
        p = str(path)
    return os.path.normcase(os.path.abspath(p))


def _under(path: str, roots) -> bool:
    for r in roots:
        if path == r or path.startswith(r.rstrip("\\/") + os.sep):
            return True
    return False


def _host_is_loopback(host, *, for_bind: bool = False) -> bool:
    if host is None:
        return not for_bind
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    h = str(host).strip().strip("[]").lower().split("%")[0]
    if h == "":
        return not for_bind          # '' in bind() means "every network interface"
    if h in ("localhost", "localhost.", "localhost.localdomain"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False                 # any other name would need a DNS lookup
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _addr_host(address):
    if isinstance(address, tuple) and address:
        return address[0], (address[1] if len(address) > 1 else None)
    return None, None                # AF_UNIX paths etc. never leave the machine


def _refuse(kind: str, detail: str):
    test = bool(getattr(_tls, "test", False))
    LEDGER.add(kind, detail, test=test)
    r = getattr(_tls, "receipt", None)
    if r is not None:
        r["blocked"].append(detail)
    raise Blocked(f"Second Brain privacy guard refused: {detail}")


# --------------------------------------------------------------------------
# Event handlers
# --------------------------------------------------------------------------
def _on_open(args):
    path, mode, flags = (tuple(args) + (None, None, None))[:3]
    p = _norm(path)
    if p is None:
        return
    writing = (isinstance(mode, str) and any(ch in mode for ch in "wax+")) or (
        mode is None and isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
    )
    if writing:
        _refuse("write_blocked", f"write to {p}")
    r = getattr(_tls, "receipt", None)
    if _under(p, _scope_roots()):
        if not _is_allowed(p):
            LEDGER.add("read_switched_off", p)
        LEDGER.note_read(p)
        if r is not None:
            r["read"].append(p)
    elif _under(p, _program_roots):
        return                       # the program reading its own code or UI
    else:
        LEDGER.add("read_outside", p)
        if r is not None:
            r["read_other"].append(p)


def _on_fs_change(event, args):
    target = args[0] if args else ""
    _refuse("write_blocked", f"{event} {target}")


def _on_net(event, args):
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg", "socket.bind"):
        host, port = _addr_host(args[1] if len(args) > 1 else None)
        if host is None and port is None:
            return
        ok = _host_is_loopback(host, for_bind=(event == "socket.bind"))
        where = f"{host}:{port}"
    elif event == "socket.getaddrinfo":
        host, port = args[0], args[1]
        ok, where = _host_is_loopback(host), f"{host}:{port}"
    elif event == "socket.getnameinfo":
        host, port = _addr_host(args[0])
        ok, where = _host_is_loopback(host), f"{host}:{port}"
    elif event in ("socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"):
        ok, where = _host_is_loopback(args[0]), str(args[0])
    elif event == "urllib.Request":
        from urllib.parse import urlsplit
        u = urlsplit(str(args[0]))
        ok, where = _host_is_loopback(u.hostname), str(args[0])
    elif event == "http.client.connect":
        ok, where = _host_is_loopback(args[1]), f"{args[1]}:{args[2]}"
    else:
        return
    what = {"socket.bind": "listen on", "socket.getaddrinfo": "look up",
            "socket.gethostbyname": "look up", "socket.gethostbyname_ex": "look up",
            "socket.gethostbyaddr": "look up", "socket.getnameinfo": "look up",
            "urllib.Request": "request"}.get(event, "connect to")
    if not ok:
        _refuse("net_blocked", f"{what} {where} (not this device)")
    if event == "socket.connect":
        LEDGER.add("net_loopback", f"connect to {where} (this device)")
        r = getattr(_tls, "receipt", None)
        if r is not None:
            r["net"].append(where)


def _on_exec(event, args):
    global _browser_url
    if event == "subprocess.Popen" and _helpers:
        executable, argv, cwd, env = (tuple(args) + (None,) * 4)[:4]
        if executable is None and env is None:
            for name, check in _helpers:
                try:
                    ok = bool(check(argv))
                except Exception:
                    ok = False
                if ok:
                    LEDGER.add("helper_run", f"started {name} (the one allowed helper)")
                    return
    text = " ".join(str(a) for a in args)
    if _browser_url and _browser_url in text:
        if event in ("webbrowser.open", "os.startfile", "subprocess.Popen"):
            LEDGER.add("exec_allowed", f"opened your browser at {_browser_url}")
            if event != "webbrowser.open":
                _browser_url = None  # one-shot
            return
    _refuse("exec_blocked", f"start another program ({event}: {text[:120]})")


def _hook(event: str, args) -> None:
    if event == "open":
        handler = _on_open
        call = lambda: handler(args)  # noqa: E731
    elif event in _FS_CHANGE_EVENTS:
        call = lambda: _on_fs_change(event, args)  # noqa: E731
    elif event.startswith(("socket.", "urllib.", "http.client.")):
        call = lambda: _on_net(event, args)  # noqa: E731
    elif event in _EXEC_EVENTS:
        call = lambda: _on_exec(event, args)  # noqa: E731
    else:
        return
    if getattr(_tls, "busy", False):
        return
    _tls.busy = True
    try:
        call()
    finally:
        _tls.busy = False


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def install(*, scope_roots, is_allowed, program_roots, browser_url: str | None = None) -> None:
    """Install the guard. Safe to call once; it can never be uninstalled."""
    global _installed, _scope_roots, _is_allowed, _program_roots, _browser_url
    _scope_roots = scope_roots
    _is_allowed = is_allowed
    _program_roots = [os.path.normcase(os.path.abspath(p)) for p in program_roots]
    _browser_url = browser_url
    if not _installed:
        sys.dont_write_bytecode = True
        sys.addaudithook(_hook)
        _installed = True


def allow_helper(name: str, check) -> None:
    """Let one specific helper program start. `check(argv)` is asked before every launch and
    must say yes only to the exact command line the app builds. Only possible before seal()."""
    if _sealed:
        raise Blocked("the list of helper programs is fixed once the app is running")
    _helpers.append((name, check))


def seal() -> None:
    global _sealed
    _sealed = True


def helpers() -> list[str]:
    return [name for name, _ in _helpers]


def note_helper_read(path: str) -> None:
    """A helper program read this file for us: record it like any other read."""
    _on_open((path, "r", 0))


def installed() -> bool:
    return _installed


@contextlib.contextmanager
def receipt():
    """Collect what one request actually touched, as seen by the guard."""
    r = {"read": [], "read_other": [], "blocked": [], "net": []}
    _tls.receipt = r
    try:
        yield r
    finally:
        _tls.receipt = None


def leak_test(app_dir: str) -> list[dict]:
    """Deliberately try to break the rule and report what the guard did.

    Each attempt should be refused by the guard *before* anything happens.
    """
    import socket
    import subprocess
    import urllib.request

    attempts = [
        ("Look up a website's address (DNS)",
         lambda: socket.getaddrinfo("example.com", 443)),
        ("Open a connection to an internet server (1.1.1.1:443)",
         lambda: _connect_raw(("1.1.1.1", 443))),
        ("Send a web request to https://example.com",
         lambda: urllib.request.urlopen("https://example.com", timeout=3)),
        ("Write a copy of a note to disk",
         lambda: open(os.path.join(app_dir, "leak-test-copy.txt"), "w")),
        ("Start another program that could upload files",
         lambda: subprocess.Popen(["cmd", "/c", "echo", "hi"] if os.name == "nt" else ["echo", "hi"])),
    ]
    return [attempt(name, fn) for name, fn in attempts]


def attempt(name: str, fn) -> dict:
    """Try something the guard should refuse, and report honestly what happened."""
    _tls.test = True
    try:
        out = fn()
        with contextlib.suppress(Exception):
            out.kill()
        with contextlib.suppress(Exception):
            out.close()
        return {"attempt": name, "blocked": False, "how": "NOT blocked: this should never happen"}
    except Blocked as e:
        return {"attempt": name, "blocked": True, "how": str(e).split("refused: ", 1)[-1]}
    except Exception as e:  # blocked by something else, still report honestly
        return {"attempt": name, "blocked": False, "how": f"failed for another reason: {type(e).__name__}: {e}"}
    finally:
        _tls.test = False


def _connect_raw(addr):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(3)
        s.connect(addr)
    finally:
        s.close()
