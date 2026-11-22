"""
sources.py - find and read the files you have allowed.

Nothing here is cached. Every call walks the folders and reads the files
fresh, returns plain Python objects, and those objects are dropped when the
request that asked for them finishes. There is no index, no database and no
copy on disk.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field

TEXT_EXT = {".md", ".markdown", ".txt", ".text", ".org"}
CSV_EXT = {".csv"}
CAL_EXT = {".ics"}
LINK_EXT = {".url", ".webloc"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".heic", ".bmp", ".webp", ".tif", ".tiff"}
MAX_BYTES = 2_000_000
MAX_IMAGE_BYTES = 20_000_000

# Reads the text in screenshots on this device, if the app has a way to (see ocr.py).
# A function: list of image paths -> {path: [lines of text] or "why it couldn't be read"}.
# None means images aren't read at all.
OCR_READER = None
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv"}

KIND_LABEL = {
    "note": "Note", "calendar": "Calendar", "link": "Saved link", "links": "Saved links",
    "reminders": "Reminders", "draft": "Draft", "screenshot": "Screenshot", "actions": "Action list",
}


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4,
    "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11,
    "nov": 11, "december": 12, "dec": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2,
            "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4,
            "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

_DATE_PATTERNS = [
    ("iso", re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")),
    ("ical", re.compile(r"\b(20\d\d)(\d\d)(\d\d)T?\b")),
    ("dmy", re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")),
    ("d_mon", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\b\.?(?:,?\s+(20\d\d))?", re.I)),
    ("mon_d", re.compile(rf"\b({_MON})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", re.I)),
    ("by_wd", re.compile(rf"\b(?:by|before|on|next)\s+({_WD})\b", re.I)),
    ("eow", re.compile(r"\b(?:eow|end of (?:the )?week)\b", re.I)),
    ("eom", re.compile(r"\b(?:eom|end of (?:the )?month)\b", re.I)),
    ("end_mon", re.compile(rf"\bend of ({_MON})\b", re.I)),
    ("tomorrow", re.compile(r"\btomorrow\b", re.I)),
]


def _infer_year(month: int, day: int, ref: dt.date) -> dt.date | None:
    try:
        d = dt.date(ref.year, month, day)
    except ValueError:
        return None
    if (d - ref).days < -183:
        d = d.replace(year=d.year + 1)
    elif (d - ref).days > 183:
        d = d.replace(year=d.year - 1)
    return d


def _last_day(year: int, month: int) -> dt.date:
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def find_dates(text: str, ref: dt.date) -> list[tuple[int, int, dt.date, str]]:
    """All dates mentioned in `text` as (start, end, date, kind). `ref` resolves
    missing years and relative phrases ("by Fri")."""
    found: list[tuple[int, int, dt.date, str]] = []
    taken: list[tuple[int, int]] = []

    def free(a, b):
        return all(b <= s or a >= e for s, e in taken)

    for kind, rx in _DATE_PATTERNS:
        for m in rx.finditer(text):
            if not free(m.start(), m.end()):
                continue
            d = None
            try:
                if kind in ("iso", "ical"):
                    d = dt.date(int(m[1]), int(m[2]), int(m[3]))
                elif kind == "dmy":
                    day, mon = int(m[1]), int(m[2])
                    if not (1 <= mon <= 12 and 1 <= day <= 31):
                        continue
                    if m[3]:
                        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
                        d = dt.date(y, mon, day)
                    else:
                        d = _infer_year(mon, day, ref)
                elif kind == "d_mon":
                    mon, day = MONTHS[m[2].lower()], int(m[1])
                    d = dt.date(int(m[3]), mon, day) if m[3] else _infer_year(mon, day, ref)
                elif kind == "mon_d":
                    mon, day = MONTHS[m[1].lower()], int(m[2])
                    d = dt.date(int(m[3]), mon, day) if m[3] else _infer_year(mon, day, ref)
                elif kind == "by_wd":
                    wd = WEEKDAYS[m[1].lower()]
                    ahead = (wd - ref.weekday()) % 7 or 7
                    d = ref + dt.timedelta(days=ahead)
                elif kind == "eow":
                    ahead = (4 - ref.weekday()) % 7
                    d = ref + dt.timedelta(days=ahead)
                elif kind == "eom":
                    d = _last_day(ref.year, ref.month)
                elif kind == "end_mon":
                    mon = MONTHS[m[1].lower()]
                    y = ref.year + (1 if mon < ref.month - 6 else 0)
                    d = _last_day(y, mon)
                elif kind == "tomorrow":
                    d = ref + dt.timedelta(days=1)
            except ValueError:
                d = None
            if d:
                found.append((m.start(), m.end(), d, kind))
                taken.append((m.start(), m.end()))
    found.sort()
    return found


def fmt_date(d: dt.date | None) -> str:
    if not d:
        return "undated"
    return f"{d.day} {d.strftime('%b')}" + ("" if d.year == dt.date.today().year else f" {d.year}")


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@dataclass
class Doc:
    path: str                    # absolute path (original case)
    display: str                 # path relative to the folder you allowed
    kind: str
    title: str
    date: dt.date
    date_source: str             # 'file name' | 'first lines' | 'file time (guessed)'
    lines: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)   # names from Attendees:/With: lines
    events: list[dict] = field(default_factory=list)  # calendar only
    url: str | None = None                            # .url files
    owners: list[str] = field(default_factory=list)   # action lists: who owns each row (not who the file is about)


def kind_of(path: str) -> str | None:
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    parts = [p.lower() for p in os.path.normpath(path).split(os.sep)[:-1]]
    if ext in CAL_EXT:
        return "calendar"
    if ext in CSV_EXT:
        return "actions"
    if ext in LINK_EXT:
        return "link"
    if ext in IMAGE_EXT:
        return "screenshot"
    if ext in TEXT_EXT:
        if "draft" in name or any(p in ("drafts", "draft") for p in parts):
            return "draft"
        if re.search(r"remind|todo|to-do|tasks", name):
            return "reminders"
        if re.search(r"links?\b|bookmark", name) or any(p in ("links", "bookmarks") for p in parts):
            return "links"
        return "note"
    return None


_PRIVATE_RX = re.compile(r"(?<![a-z])(private|confidential)(?![a-z])", re.I)


def is_private(display: str) -> bool:
    """A file is private if its name, or a folder it sits in (inside the allowed folder), says
    "private" or "confidential". Decided from the name alone, so a private note is never
    opened to find out."""
    return bool(_PRIVATE_RX.search(display.replace("\\", "/")))


def norm_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def inventory(roots: list[str], switched_off: set[str], switched_on: set[str] = frozenset()) -> list[dict]:
    """List what is in the allowed folders (names and sizes only; nothing is opened).
    Private files stay off until you switch them on (their key is in switched_on)."""
    out = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                k = kind_of(p)
                readable, why_not = True, ""
                if k is None:
                    readable, why_not = False, "file type not supported"
                elif k == "screenshot":
                    if OCR_READER is None:
                        readable, why_not = False, "image - no on-device text recognition yet"
                    elif st.st_size > MAX_IMAGE_BYTES:
                        readable, why_not = False, "image larger than 20 MB"
                elif st.st_size > MAX_BYTES:
                    readable, why_not = False, "larger than 2 MB"
                key = norm_key(p)
                display = os.path.relpath(p, root).replace(os.sep, "/")
                private = is_private(display)
                locked = private and key not in switched_on and key not in switched_off
                out.append({
                    "path": p, "key": key, "root": root,
                    "display": display,
                    "kind": k or "other", "kind_label": KIND_LABEL.get(k or "", "Other"),
                    "size": st.st_size,
                    "modified": dt.date.fromtimestamp(st.st_mtime).isoformat(),
                    "readable": readable, "why_not": why_not,
                    "allowed": readable and key not in switched_off and not locked,
                    "switched_off": key in switched_off,
                    "private": private, "private_locked": locked,
                })
    return out


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


_ATTENDEE_RX = re.compile(r"^\s*(?:attendees|with|people|present|who)\s*[:\-]\s*(.+)$", re.I)
_DATE_LINE_RX = re.compile(r"^\s*(?:date|when)\s*[:\-]\s*(.+)$", re.I)


def _split_names(s: str) -> list[str]:
    parts = re.split(r",|&|\band\b|\+|;|/", s)
    names = []
    for p in parts:
        p = re.sub(r"\(.*?\)", "", p).strip(" .-")
        if p and len(p) < 40:
            names.append(p)
    return names


_CSV_COLS = {
    "action": ("action", "task", "todo", "to do", "item", "what", "description"),
    "owner": ("owner", "who", "assignee", "assigned to", "person", "lead"),
    "due": ("due", "due date", "deadline", "by", "date", "when"),
    "status": ("status", "done", "state", "complete", "completed"),
}
_DONE_WORDS = {"done", "complete", "completed", "closed", "finished", "yes", "y", "true", "x", "✅"}


def csv_rows_to_lines(text: str) -> tuple[list[str], list[str]]:
    """Turn a spreadsheet action list into note-style lines the tagger understands:
    '- [ ] Dana to send the cost sheet by 2026-11-13'. Returns (lines, owners)."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], []
    header = [c.strip().lower() for c in rows[0]]
    col = {}
    for key, names in _CSV_COLS.items():
        for i, h in enumerate(header):
            if h in names and i not in col.values():
                col[key] = i
                break
    has_header = "action" in col
    body = rows[1:] if has_header else rows
    # one output line per file line, so "line 3" still means line 3 of the spreadsheet
    lines, owners = (["# " + ", ".join(rows[0])] if has_header else []), []
    for r in body:
        cell = lambda k: (r[col[k]].strip() if k in col and col[k] < len(r) else "")  # noqa: E731
        action = cell("action") if has_header else " ".join(c.strip() for c in r if c.strip())
        if not action:
            lines.append("")
            continue
        owner, due, status = cell("owner"), cell("due"), cell("status").lower()
        who = "me" if owner.lower() in ("", "me", "i", "you", "myself") else owner
        if who != "me":
            owners.append(owner)
        # shown almost exactly as the row reads: "Send Tom the welcome pack · me · by 2026-11-25"
        line = f"{action} · {who}" + (f" · by {due}" if due else "")
        lines.append(f"- [{'x' if status in _DONE_WORDS else ' '}] {line}")
    return lines, owners


def read_doc(f: dict, text: str | None = None) -> Doc | None:
    """Read one file. For a screenshot, `text` is what the on-device text reader found in it."""
    path, kind = f["path"], f["kind"]
    mtime = dt.date.fromisoformat(f["modified"])
    if kind == "calendar":
        return _read_ics(f, mtime)
    if kind == "actions":
        lines, owners = csv_rows_to_lines(_read_text(path))
        title = os.path.splitext(os.path.basename(path))[0]
        return Doc(path, f["display"], kind, title, mtime, "file time (guessed)", lines=lines, owners=owners)
    if kind == "link":
        text = _read_text(path)
        m = re.search(r"^\s*URL\s*=\s*(\S+)", text, re.M | re.I) or re.search(r"https?://\S+", text)
        url = (m.group(1) if m and m.lastindex else m.group(0)) if m else None
        title = os.path.splitext(os.path.basename(path))[0]
        return Doc(path, f["display"], kind, title, mtime, "file time (guessed)",
                   lines=[f"{title} — {url}"] if url else [title], url=url)

    if text is None:
        text = _read_text(path)
    lines = text.splitlines()
    name = os.path.splitext(os.path.basename(path))[0]

    # date: file name > first lines > file time
    date, src = None, ""
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", name)
    if m:
        try:
            date, src = dt.date(int(m[1]), int(m[2]), int(m[3])), "file name"
        except ValueError:
            date = None
    if date is None and kind not in ("reminders", "links"):
        for ln in lines[:4]:
            ds = find_dates(ln, mtime)
            # only a date that heads the line ("13/10/2026", "Date: ...") or a
            # short title line ("atlas standup 17/11") dates the whole file
            if ds and ds[0][3] in ("iso", "dmy", "d_mon", "mon_d") and (
                    ds[0][0] < 3 or re.match(r"^\s*(date|when)\b", ln, re.I) or len(ln.strip()) <= 30):
                date, src = ds[0][2], "first lines"
                break
    if date is None:
        date, src = mtime, "file time (guessed)"

    title = ""
    for ln in lines:
        s = ln.strip()
        if s:
            title = re.sub(r"^#+\s*", "", s)
            break
    if not title or kind in ("reminders", "links", "draft") or len(title) > 60:
        title = re.sub(r"^20\d\d-\d\d-\d\d\s*", "", name) or name

    people: list[str] = []
    for ln in lines[:8]:
        am = _ATTENDEE_RX.match(ln)
        if am:
            people += _split_names(am.group(1))
    # "20 Oct 2026 - w/ Marco Bianchi (account mgr), Priya"
    for ln in lines[:3]:
        wm = re.search(r"\bw/\s*(.+)$", ln)
        if wm:
            people += _split_names(wm.group(1))
    return Doc(path, f["display"], kind, title, date, src, lines=lines, people=people)


def _ics_unescape(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _ics_dt(v: str) -> dt.datetime | None:
    v = v.strip().rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return dt.datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def _read_ics(f: dict, mtime: dt.date) -> Doc:
    raw = _read_text(f["path"]).replace("\r\n", "\n")
    unfolded = re.sub(r"\n[ \t]", "", raw).split("\n")
    events, cur, me = [], None, None
    for i, ln in enumerate(unfolded, 1):
        if ln.startswith("BEGIN:VEVENT"):
            cur = {"attendees": [], "line": i}
        elif ln.startswith("END:VEVENT") and cur is not None:
            if cur.get("start"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            key, val = ln.split(":", 1)
            name = key.split(";")[0].upper()
            params = dict(p.split("=", 1) for p in key.split(";")[1:] if "=" in p)
            if name == "SUMMARY":
                cur["title"] = _ics_unescape(val)
            elif name == "DESCRIPTION":
                cur["description"] = _ics_unescape(val)
            elif name == "DTSTART":
                cur["start"] = _ics_dt(val)
            elif name == "UID":
                cur["uid"] = val.strip()
            elif name == "ATTENDEE":
                cur["attendees"].append(params.get("CN", val.replace("mailto:", "")).strip('"'))
            elif name == "ORGANIZER":
                me = params.get("CN", "").strip('"') or me
    for e in events:
        e["id"] = e.get("uid") or f"{e['start'].isoformat()}-{e.get('title', '')}"
        e["date"] = e["start"].date()
        e["me"] = me
    return Doc(f["path"], f["display"], "calendar", os.path.basename(f["path"]), mtime,
               "file time (guessed)", lines=unfolded, events=events)


def read_all(files: list[dict]) -> list[Doc]:
    """Read every allowed, readable file. Returns fresh objects every time.
    Screenshots are read in one go by the on-device text reader, if there is one; an image
    it can't read is marked unreadable (with the reason) so answers can say so."""
    images = [f for f in files if f["allowed"] and f["kind"] == "screenshot"]
    texts = OCR_READER([f["path"] for f in images]) if images and OCR_READER else {}
    docs = []
    for f in files:
        if not f["allowed"]:
            continue
        if f["kind"] == "screenshot":
            got = texts.get(f["path"])
            if not isinstance(got, list) or not any(ln.strip() for ln in got):
                f["readable"], f["allowed"] = False, False
                f["why_not"] = got if isinstance(got, str) and got else "no text found in this image"
                continue
            d = read_doc(f, text="\n".join(got))
        else:
            d = read_doc(f)
        if d:
            docs.append(d)
    return docs


def cloud_sync_warning(path: str) -> str | None:
    """Is this folder inside a cloud-synced folder? If so, the *sync app*
    (not this assistant) is already copying it off the device."""
    p = os.path.normcase(os.path.abspath(path))
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(env)
        if root and (p == os.path.normcase(root) or p.startswith(os.path.normcase(root) + os.sep)):
            return "OneDrive"
    parts = [s.lower() for s in os.path.normpath(path).split(os.sep)]
    for name, label in (("onedrive", "OneDrive"), ("dropbox", "Dropbox"), ("google drive", "Google Drive"),
                        ("googledrive", "Google Drive"), ("icloud drive", "iCloud Drive"),
                        ("iclouddrive", "iCloud Drive"), ("box", "Box")):
        if any(s == name or s.startswith(name + " -") or s.startswith(name + "-") for s in parts):
            return label
    return None
