"""
brain.py - turns scattered notes into help, without remembering anything.

Every public function takes freshly read Docs and returns plain data for one
answer. There is no module-level state, no cache and no index: when the answer
has been sent, everything computed here is garbage.

How it helps (no cloud model needed):
  * Tags each line of your notes: action, decision, question, risk, done.
  * Connects lines about the same thing across files and weeks into "threads"
    (e.g. a promise made in a 1:1, repeated in a reminder, still not done).
  * Spots things that changed: the same subject with a different number or
    date later on, or a later note saying "moved", "on hold", "revised"...
  * Fills gaps in half-written drafts from what your other notes already say.
  * Says plainly when it cannot find something, and what it could not check.
Every item it shows is a quote from your notes with the file and line.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from sources import MONTHS, WEEKDAYS, Doc, find_dates, fmt_date

# --------------------------------------------------------------------------
# Words
# --------------------------------------------------------------------------
STOP = set("""
a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those i me my we our you your he she they them his her their there here not no yes do
does did have has had will would should could can may might just also very really about into over under
than too up down out off again more most some any each all both few other such only own same s t d ll m
re ve don didn im ive ill weve were lets per via vs etc ok okay what when where who whom which why how
w hmm tho though pls please get got go going make made one two us once before after basically actually
haven hasn hasnt havent didn isn wasn won can couldn shouldn wouldn aren weren yet ago she he her him
still sure back came come
""".split())

# low-information words in meeting notes; ignored when working out a topic
GENERIC = set("""
meeting meet call sync notes note update quick thing things stuff today said says say need needs want
wants like think thinks new also still now next first end time sure day days week weeks month group
agenda date dates item items catch chat oneonone weekly daily standup check checkin session discussion
review talk topic plan planning team context thanks follow followup again since ask asked know start
""".split())

PHRASES = [
    (re.compile(r"\b1\s*[:\-]\s*1s?\b|\bone[ -]?(?:on|to)[ -]?one\b", re.I), " oneonone "),
    (re.compile(r"\btech[ -]?lead\b|\btl\b", re.I), " techlead "),
    (re.compile(r"\bsingle sign[ -]?on\b", re.I), " sso "),
    (re.compile(r"\bpurchase order\b", re.I), " po "),
    (re.compile(r"\bgo[ -]?live\b", re.I), " launch "),
    (re.compile(r"\bf/u\b|\bfollow[ -]?up\b", re.I), " followup "),
    (re.compile(r"\bw/", re.I), " with "),
    (re.compile(r"\beow\b|\bend of (?:the )?week\b", re.I), " endofweek "),
    (re.compile(r"\bsign[ -]?off\b", re.I), " signoff "),
    (re.compile(r"\bon[ -]?call\b", re.I), " oncall "),
]

SYN = {
    "supplier": "vendor", "suppliers": "vendor", "vendors": "vendor", "provider": "vendor",
    "cost": "budget", "costs": "budget", "spend": "budget", "funding": "budget", "money": "budget",
    "price": "pricing", "prices": "pricing", "priced": "pricing", "quoted": "pricing", "quote": "pricing",
    "discount": "pricing", "expensive": "pricing", "cheap": "pricing", "cheaper": "pricing",
    "hire": "hiring", "hires": "hiring", "headcount": "hiring", "recruit": "hiring", "recruiting": "hiring",
    "release": "launch", "launching": "launch", "launched": "launch", "live": "launch",
    "delay": "slip", "delayed": "slip", "postpone": "slip", "postponed": "slip", "push": "slip", "pushed": "slip",
    "mtg": "meeting", "mtgs": "meeting", "meetings": "meeting",
    "convo": "conversation", "conversations": "conversation",
    "promotion": "techlead", "promo": "techlead",
    "wks": "week", "wk": "week", "weeks": "week", "hrs": "hour", "hr": "hour", "hours": "hour",
    "mgr": "manager", "db": "database", "onboard": "onboarding", "onboarded": "onboarding",
    "starter": "onboarding", "starts": "start", "started": "start", "starting": "start",
    "api's": "api", "apis": "api", "limits": "limit", "decided": "decision", "decide": "decision",
}


def stem(w: str) -> str:
    if w in SYN:
        w = SYN[w]
    if len(w) <= 4 or not w.isalpha():
        return w
    for suf in ("ings", "ing", "edly", "ed", "ies", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + ("y" if suf == "ies" else "")
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


_TOKEN_RX = re.compile(r"[a-z0-9£$€]+(?:'[a-z]+)?")


def tokens(text: str) -> list[str]:
    t = text.lower()
    for rx, rep in PHRASES:
        t = rx.sub(rep, t)
    out = []
    for w in _TOKEN_RX.findall(t):
        w = w.split("'")[0]
        if not w or w in STOP:
            continue
        out.append(stem(w))
    return out


# --------------------------------------------------------------------------
# Tagging a line
# --------------------------------------------------------------------------
NEG_RX = re.compile(r"\b(not|n't|haven'?t|hasn'?t|hasnt|havent|didn'?t|didnt|isn'?t|isnt|wasn'?t|"
                    r"still|yet to|pending|partly|partially|waiting)\b|\?", re.I)
DONE_RX = re.compile(r"\[x\]|✅|✔|☑|\b(done|sent|completed?|sorted|closed|scoped|raised|fixed|"
                     r"resolved|booked|shipped|delivered|submitted|finished)\b", re.I)
DECISION_RX = re.compile(r"\b(decision|decided|agreed|going with|go with|approved|signed off|settled on|"
                         r"chose|chosen|confirmed|final call|green ?lit|said yes)\b", re.I)
NOT_A_DECISION_RX = re.compile(r"\bneed(?:s)?\s+(?:a|an|to)\b[^.]*\b(decision|decide)\b|\bpending\s+decision\b", re.I)
QUESTION_RX = re.compile(r"\?|\b(tbd|tbc|open question|unclear|not sure|unknown|to be confirmed|"
                         r"who owns|find out)\b", re.I)
RISK_RX = re.compile(r"\b(at risk|risk(?! summary)|blockers?|blocked|concern(?:ed)?|worried|worry|problem|"
                     r"issue|slipp?(?:ing|ed)?|delay(?:ed)?|behind|burnout|tight|freeze)\b", re.I)
ACTION_RX = [
    (re.compile(r"^\s*(?:[-*•]\s*)?\[\s\]"), "unticked box"),
    (re.compile(r"^\s*(?:[-*•]\s*)?(?:ai|a/i|action|todo|to-do|next|follow[ -]?up|f/u)\s*:", re.I), "action label"),
    (re.compile(r"\b(need to|needs to|i'll|i will|i said i'd|i said i would|remember to|"
                r"don't forget|chase|to do|must)\b", re.I), "says it needs doing"),
    (re.compile(r"^\s*(?:[-*•]\s*)?(?:me|i)\s*(?::|-|to\b)", re.I), "assigned to you"),
    (re.compile(r"\b(?:ask|check w(?:ith|/)?)\s+\w+", re.I), "says to ask someone"),
    (re.compile(r"^\s*(?:[-*•]\s*)?\w+\s*:\s*wants\b|\bwants\b.*\b(summary|update|report|plan|deck|doc)\b", re.I),
     "someone asked you for it"),
    (re.compile(r"\bdue\b", re.I), "has a due date"),
]
DECISION_NEG_RX = re.compile(r"\b(not|n't|hasnt|havent|didnt|isnt|wasnt|still|yet)\b|\?", re.I)
CHANGE_RX = re.compile(r"\b(instead|reversed|no longer|changed|scrap(?:ped)?|switch(?:ed)? to|"
                       r"push(?:ed)? (?:back|to)|move[ds]? (?:\w+ )?to|moving to|on hold|paused|revised|"
                       r"freeze|cancel(?:led)?|dropped)\b", re.I)
MONEY_RX = re.compile(r"(?<![\w.])([£$€])?\s?(\d+(?:\.\d+)?)\s?(k|m|bn)\b|([£$€])\s?(\d[\d,]*(?:\.\d+)?)", re.I)
URL_RX = re.compile(r"https?://[^\s)>\]]+")
SECTION_RX = re.compile(r"^\s*(?:#+\s*)?(actions?|action items|next steps|to ?dos?|open q\w*|questions|"
                        r"decisions?|risks?|asks?)\s*:?\s*$", re.I)
SELF_RX = re.compile(r"\b(i'll|i will|i said i'd|i said i would|i need to|i haven't|need to do this)\b|"
                     r"^\s*(?:[-*•]\s*)?(?:\[.\]\s*)?(?:me|i)\s*(?::|-|to\b)|\b(?:ai|action)\s*:\s*me\b", re.I)


def money_values(text: str) -> list[tuple[int, float]]:
    out = []
    for m in MONEY_RX.finditer(text):
        if m.group(2):
            if not m.group(1) and not m.group(3):
                continue
            v = float(m.group(2)) * {"k": 1e3, "m": 1e6, "bn": 1e9}.get((m.group(3) or "").lower(), 1)
        else:
            v = float(m.group(5).replace(",", ""))
        out.append((m.start(), v))
    return out


def money_str(v: float) -> str:
    return f"£{v / 1000:g}k" if v >= 1000 else f"£{v:g}"


@dataclass
class Frag:
    id: int
    doc: Doc
    line: int
    raw: str
    text: str
    date: dt.date
    date_guessed: bool
    section: str
    toks: list[str]
    tags: set = field(default_factory=set)
    why: dict = field(default_factory=dict)
    owner: str | None = None
    due: dt.date | None = None
    people: set = field(default_factory=set)
    money: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    url: str | None = None

    @property
    def done(self) -> bool:
        return "done" in self.tags


def _clean(line: str) -> str:
    s = re.sub(r"^\s*(?:[-*•]\s*)?(?:\[[ xX]\]\s*)?", "", line)
    s = re.sub(r"^#+\s*", "", s)
    return s.replace("**", "").strip()


class Roster:
    """People named in your notes and calendar. First names are the handle."""

    def __init__(self) -> None:
        self.full: dict[str, str] = {}
        self.me: str | None = None

    def add(self, name: str) -> None:
        name = name.strip()
        if not name or name.lower() in ("me", "i", "myself", "you"):
            return
        first = re.split(r"\s+", name)[0].strip(".,()").lower()
        if len(first) < 2 or not first.isalpha() or first in STOP:
            return
        if first not in self.full or len(name) > len(self.full[first]):
            self.full[first] = name if " " in name else name.capitalize()

    def in_text(self, text: str) -> set[str]:
        low = text.lower()
        return {f for f in self.full if re.search(rf"\b{re.escape(f)}\b", low)}

    def name(self, first: str | None) -> str:
        if first is None:
            return "unassigned"
        if first == "you":
            return "You"
        return self.full.get(first, first.capitalize()).split()[0]


def build_roster(docs: list[Doc]) -> Roster:
    r = Roster()
    for d in docs:
        for p in d.people + d.owners:
            r.add(p)
        for e in d.events:
            for a in e["attendees"]:
                r.add(a)
            if e.get("me"):
                r.me = e["me"]
        if d.kind != "calendar":
            for ln in d.lines:
                for m in re.finditer(r"(?<![\w.])@([A-Za-z]{2,})\b(?![.@])", ln):
                    r.add(m.group(1))
    if r.me:
        r.full.pop(r.me.split()[0].lower(), None)
    return r


def build_frags(docs: list[Doc], roster: Roster) -> list[Frag]:
    frags: list[Frag] = []
    for d in docs:
        if d.kind == "calendar":
            continue
        section = ""
        for i, raw in enumerate(d.lines, 1):
            s = raw.strip()
            if not s:
                continue
            if i <= 3 and (s.lstrip("# ").strip() == d.title.strip() or _DATEISH.match(s) or
                           (re.search(r"\bw/\s*[A-Z]", s) and find_dates(s, d.date))):
                continue
            if re.match(r"^\s*(attendees|with|people|present|date|when|draft)\b", s, re.I) and i <= 4:
                continue
            sm = SECTION_RX.match(s)
            if sm:
                section = sm.group(1).lower()
                continue
            if s.startswith("#") or s in ("-", "*"):
                section = "" if s.startswith("#") else section
                continue
            if s.startswith("[InternetShortcut]"):
                continue
            text = _clean(raw)
            if len(text) < 3:
                continue
            date, guessed = d.date, d.date_source.startswith("file time")
            lead = find_dates(text[:22], d.date)
            if lead and lead[0][3] in ("iso", "dmy", "d_mon", "mon_d") and lead[0][0] < 3:
                date, guessed = lead[0][2], False   # "12 Nov - corridor chat..." dates just this line
            f = Frag(len(frags), d, i, raw, text, date, guessed, section, tokens(text))
            _tag(f, d, roster)
            frags.append(f)
    return frags


_DATEISH = re.compile(r"^\s*(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*\s+)?\d{1,2}(?:/\d{1,2}/\d{2,4}|\s+\w+\s+20\d\d)\s*$", re.I)


def _tag(f: Frag, d: Doc, roster: Roster) -> None:
    t, raw = f.text, f.raw
    f.people = roster.in_text(t)
    f.money = money_values(t)
    f.dates = [(s, dd, k) for s, _, dd, k in find_dates(t, f.date)]
    u = URL_RX.search(t)
    if u or d.kind in ("link", "links"):
        f.url = u.group(0) if u else d.url
        if f.url:
            f.tags.add("link")
            f.why["link"] = "a saved link"
            return
    negated = bool(NEG_RX.search(t))
    m = DONE_RX.search(raw)
    if m and not (negated and m.group(0) not in ("[x]", "[X]", "✅", "✔", "☑")):
        f.tags.add("done")
        f.why["done"] = f"says “{m.group(0)}”"
    m = DECISION_RX.search(t)
    if m and not NOT_A_DECISION_RX.search(t) and not DECISION_NEG_RX.search(t):
        f.tags.add("decision")
        f.why["decision"] = f"says “{m.group(0)}”"
        if re.search(r"\bpending\b|\bif\b|\bsubject to\b", t, re.I):
            f.tags.add("tentative")
    m = QUESTION_RX.search(t)
    if m or f.section.startswith(("open q", "question")):
        f.tags.add("question")
        f.why["question"] = (f"says “{m.group(0)}”" if m and m.group(0) != "?" else
                             "ends with a question mark" if m else "listed under open questions")
    m = RISK_RX.search(t)
    if m:
        f.tags.add("risk")
        f.why["risk"] = f"says “{m.group(0)}”"
    if "done" not in f.tags:
        reason = None
        if f.section.startswith(("action", "next", "to")):
            reason = f"listed under “{f.section}”"
        if not reason:
            for rx, label in ACTION_RX:
                if rx.search(raw):
                    reason = label
                    break
        if not reason:
            for first in roster.full:
                if re.search(rf"\b{first}\s+(?:to|will|needs to|should)\s+(?!be\b)\w+", t, re.I):
                    reason = f"says {roster.name(first)} will do something"
                    break
        if not reason and d.kind == "reminders":
            reason = "in your reminders"
        if reason:
            f.tags.add("action")
            f.why["action"] = reason
    # who owns it (a spreadsheet row says so in its own column)
    if d.kind == "actions" and " · " in t:
        who = t.split(" · ")[1].strip().lower()
        f.owner = "you" if who in ("me", "i", "you") else (who.split()[0] if who.split() else None)
    if f.owner is None and f.tags & {"action", "done", "question"}:
        for first in roster.full:
            if re.search(rf"(?:^|[\s(@]){first}\s+(?:to|will|needs to|should)\s+(?!be\b)\w+", t, re.I):
                f.owner = first
                break
        if f.owner is None and (SELF_RX.search(raw) or (d.kind == "reminders") or
                                re.search(r"\b(chase|ask|check w)\b", t, re.I) or
                                re.search(r"\bwants\b", t, re.I) and "action" in f.tags):
            f.owner = "you"
        if f.owner is None and "action" in f.tags and not d.people and d.kind in ("note", "reminders"):
            f.owner = "you"   # an unassigned to-do in your own scratch notes is most likely yours
    # due date
    if "action" in f.tags:
        dm = re.search(r"\b(?:by|before|until|due)\b", t, re.I)
        if dm:
            after = [dd for s, dd, k in f.dates if s >= dm.start()]
            if after:
                f.due = after[0]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
_CAP_RX = re.compile(r"(?<![.!?:]\s)(?<!^)(?<![.!?:])\b([A-Z][a-z]{2,})\b")
_NOT_ENT = set(MONTHS_AND_DAYS := """jan feb mar apr may jun jul aug sep sept oct nov dec january february march
april june july august september october november december mon tue wed thu fri sat sun monday tuesday
wednesday thursday friday saturday sunday the this that and but quick""".split())


class Index:
    """Throw-away BM25 statistics for one request."""

    def __init__(self, frags: list[Frag], roster: Roster):
        self.frags = frags
        self.roster = roster
        self.N = max(1, len(frags))
        self.df: dict[str, int] = defaultdict(int)
        for f in frags:
            for w in set(f.toks):
                self.df[w] += 1
        self.avgdl = sum(len(f.toks) for f in frags) / self.N if frags else 1.0
        # named things (products, projects, companies): capitalised mid-sentence somewhere
        self.ent: set[str] = set()
        for f in frags:
            for m in _CAP_RX.finditer(f.text):
                w = m.group(1).lower()
                if w not in _NOT_ENT and w not in roster.full:
                    self.ent.add(stem(w))

    def idf(self, w: str) -> float:
        return math.log(1 + (self.N - self.df.get(w, 0) + 0.5) / (self.df.get(w, 0) + 0.5))

    def weight(self, w: str) -> float:
        if w in GENERIC or w.isdigit():
            return 0.25 * self.idf(w)
        if w in self.roster.full:
            return 0.6 * self.idf(w)
        if re.match(r"^[£$€]?\d", w):
            return 0.3 * self.idf(w)
        return self.idf(w)

    def bm25(self, q: dict[str, float], f: Frag, k1: float = 1.2, b: float = 0.6) -> float:
        if not q:
            return 0.0
        tf: dict[str, int] = defaultdict(int)
        for w in f.toks:
            tf[w] += 1
        dl = len(f.toks) or 1
        s = 0.0
        for w, qw in q.items():
            n = tf.get(w, 0)
            if n:
                s += qw * self.idf(w) * n * (k1 + 1) / (n + k1 * (1 - b + b * dl / self.avgdl))
        return s

    def sim(self, a: Frag, b: Frag) -> float:
        A, B = set(a.toks), set(b.toks)
        shared = A & B
        if not shared or all(w in GENERIC or w in self.roster.full or w[0].isdigit() for w in shared):
            return 0.0
        wa = sum(self.weight(w) for w in A) or 1
        wb = sum(self.weight(w) for w in B) or 1
        return sum(self.weight(w) for w in shared) / min(wa, wb)


# --------------------------------------------------------------------------
# Threads: the same thing mentioned in several places
# --------------------------------------------------------------------------
@dataclass
class Thread:
    frags: list[Frag]
    kind: str

    @property
    def first(self) -> Frag:
        return self.frags[0]

    @property
    def last(self) -> Frag:
        return self.frags[-1]


def build_threads(ix: Index, kinds: set[str], threshold: float = 0.42) -> list[Thread]:
    """Link lines that talk about the same thing (connected components of
    'similar enough' pairs), however far apart in time or files they are."""
    pool = sorted((f for f in ix.frags if f.tags & kinds), key=lambda f: (f.date, f.id))
    parent = list(range(len(pool)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            if ix.sim(pool[i], pool[j]) >= threshold:
                parent[find(i)] = find(j)
    comp: dict[int, list[Frag]] = defaultdict(list)
    for i, f in enumerate(pool):
        comp[find(i)].append(f)
    groups = list(comp.values())
    out = []
    for g in groups:
        g.sort(key=lambda f: (f.date, f.id))
        tags = set().union(*(f.tags for f in g))
        kind = "action" if "action" in tags else "question" if "question" in tags else (
            "decision" if "decision" in tags else "risk" if "risk" in tags else "done")
        out.append(Thread(g, kind))
    return out


def thread_status(t: Thread) -> str:
    """'done' if the most recent mention says it's done, else 'open'."""
    latest = max(t.frags, key=lambda f: (f.date, f.id))
    same_day = [f for f in t.frags if f.date == latest.date]
    if any(f.done for f in same_day) and not any(("action" in f.tags or "question" in f.tags) and not f.done
                                                for f in same_day):
        return "done"
    return "open"


def thread_owner(t: Thread) -> str | None:
    for f in reversed(t.frags):
        if f.owner:
            return f.owner
    return None


def thread_due(t: Thread) -> dt.date | None:
    dues = [f.due for f in t.frags if f.due]
    return max(dues) if dues else None


# --------------------------------------------------------------------------
# Changes: the same subject with a different value later, or "moved/on hold"
# --------------------------------------------------------------------------
SUBJECT_STOP = {stem(w) for w in """confirm confirmed approve approved agree agreed decision send sent raise raised ask
move moving moved push need want expect remember check chase said think new revise revised now target update sign
signoff go going start get set open close done due only cover covers top extra higher more less over under year
month week day end anything original amount""".split()}


def _near(f: Frag, pos: int, span: int = 26) -> set[str]:
    seg = f.text[max(0, pos - span): pos + span]
    return {w for w in tokens(seg) if w not in GENERIC and not w[0].isdigit() and w[0] not in "£$€"
            and w not in _NOT_ENT}


def _entities(ix: "Index", f: Frag, near: set[str]) -> set[str]:
    e = near & ix.ent
    return e or (set(tokens(f.doc.title)) & ix.ent)


def _valued(f: Frag) -> list[tuple[str, object, set]]:
    """Numbers and dates in a line, each with the words right next to it."""
    out: list[tuple[str, object, set]] = [("money", v, _near(f, p)) for p, v in f.money]
    for p, d, k in f.dates:
        if k in ("iso", "dmy", "d_mon", "mon_d") and not (p < 3 and d == f.date):
            out.append(("date", d, _near(f, p)))
    return out


def _vfmt(kind: str, v) -> str:
    return money_str(v) if kind == "money" else fmt_date(v)


def find_changes(ix: Index, frags: list[Frag] | None = None) -> list[dict]:
    """Pairs of notes about the same subject that say different things.

    A value change needs the *same subject word* right next to a *different*
    number/date in both lines ("Budget £40k approved" vs "revised costs now
    £55k"). A wording change needs an earlier decision and a later, closely
    matching line that says "on hold", "moved to", "revised", "freeze"...
    """
    frags = frags if frags is not None else ix.frags
    cand = [f for f in frags if "link" not in f.tags]
    names = set(ix.roster.full)
    vals = {f.id: _valued(f) for f in cand}
    pairs = []
    for i, a in enumerate(cand):
        for b in cand[i + 1:]:
            old, new = (a, b) if (a.date, a.id) <= (b.date, b.id) else (b, a)
            if old.date == new.date:
                continue
            s = ix.sim(a, b)
            if s < 0.22:
                continue
            found = None
            for k1, v1, n1 in vals[old.id]:
                for k2, v2, n2 in vals[new.id]:
                    subj = (n1 & n2) - names - SUBJECT_STOP
                    if k1 != k2 or not subj:
                        continue
                    e1, e2 = _entities(ix, old, n1), _entities(ix, new, n2)
                    if e1 and e2 and not (e1 & e2):
                        continue          # same word, different thing (Kestrel's price vs Brightline's)
                    if v1 == v2:
                        found = "agree"
                        break
                    found = found or (k1, subj)
                if found == "agree":
                    break
            if found and found != "agree":
                key = (found[0], max(found[1], key=lambda w: (ix.idf(w), w)))
                pairs.append((old, new, found[0], found[1], key, found[1]))
                continue
            m = CHANGE_RX.search(new.text)
            shared = {w for w in set(old.toks) & set(new.toks) if w not in GENERIC and w not in names
                      and not w[0].isdigit() and w not in SUBJECT_STOP}
            if m and "decision" in old.tags and s >= 0.45 and len(shared) >= 2:
                pairs.append((old, new, "said", m.group(0), ("said", old.id), shared))
    # one story per subject (e.g. "launch" dates, "budget" money)
    stories: dict[tuple, list] = defaultdict(list)
    for p in pairs:
        stories[p[4]].append(p)
    out = []
    for group in stories.values():
        members = sorted({f.id: f for p in group for f in p[:2]}.values(), key=lambda f: (f.date, f.id))
        kinds = [p[2] for p in group]
        kind = max(set(kinds), key=kinds.count)
        non_draft = [m for m in members if m.doc.kind != "draft"] or members
        new = non_draft[-1]
        if kind == "said":
            said = [p for p in group if p[2] == "said"]
            old = said[0][0]
            new = max((p[1] for p in said), key=lambda f: (f.date, f.id))
            reason = f"later note says “{said[-1][3]}”"
        else:
            subject = set().union(*(p[3] for p in group if p[2] == kind))
            seq, seen_vals, first_holder = [], [], {}
            for m in members:
                for k, v, n in vals[m.id]:
                    if k == kind and n & subject:
                        if not seq or seq[-1] != v:
                            seq.append(v)
                        first_holder.setdefault(v, m)
                        break
            if len(seq) < 2:
                continue
            # "before" = the strongest statement of the first value (a decision if there is one)
            first_v = seq[0]
            holders = [m for m in members if any(k == kind and v == first_v and n & subject for k, v, n in vals[m.id])]
            old = next((m for m in reversed(holders) if "decision" in m.tags), holders[-1] if holders else members[0])
            reason = " → ".join(_vfmt(kind, v) for v in seq)
        if old is new:
            continue
        out.append({"old": old, "new": new, "members": members, "reason": reason, "kind": kind,
                    "tentative": "tentative" in new.tags, "subject": set().union(*(p[5] for p in group))})
    out.sort(key=lambda c: c["new"].date, reverse=True)
    return out


# --------------------------------------------------------------------------
# Presenting items (every item is a quote + where it came from + why)
# --------------------------------------------------------------------------
def src(f: Frag) -> dict:
    return {
        "path": f.doc.path, "file": f.doc.display, "title": f.doc.title, "kind": f.doc.kind,
        "line": f.line, "date": f.date.isoformat(), "date_label": fmt_date(f.date),
        "date_guessed": f.date_guessed,
    }


def why_text(f: Frag, matched: list[str] | None = None, extra: str = "") -> str:
    bits = []
    if matched:
        bits.append("mentions " + ", ".join(f"“{w}”" for w in matched[:3]))
    for tag in ("decision", "action", "question", "risk", "done"):
        if tag in f.why:
            label = {"decision": "counted as a decision", "action": "counted as an action",
                     "question": "counted as open", "risk": "counted as a risk",
                     "done": "counted as done"}[tag]
            bits.append(f"{label} because it {f.why[tag]}")
            break
    if f.date_guessed:
        bits.append("no date in this file, so I used the file's last-changed date")
    if extra:
        bits.append(extra)
    s = "; ".join(bits)
    return s[:1].upper() + s[1:] if s else ""


def item(f: Frag, *, why: str = "", flags: list[str] | None = None, confidence: str = "high",
         extra_sources: list[Frag] | None = None, headline: str | None = None) -> dict:
    return {
        "text": f.text, "headline": headline, "source": src(f),
        "more_sources": [src(x) for x in (extra_sources or []) if x is not f],
        "why": why, "flags": flags or [], "confidence": confidence,
    }


def _days(a: dt.date, b: dt.date) -> int:
    return (b - a).days


def _plural(n: int, w: str) -> str:
    return f"{n} {w}{'' if n == 1 else 's'}"


# --------------------------------------------------------------------------
# The moment: preparing for a meeting
# --------------------------------------------------------------------------
def list_meetings(docs: list[Doc], today: dt.date) -> list[dict]:
    evs = []
    for d in docs:
        for e in d.events:
            evs.append({
                "id": e["id"], "title": e.get("title", "(no title)"), "start": e["start"].isoformat(),
                "date_label": e["start"].strftime("%a ") + fmt_date(e["date"]) + e["start"].strftime(", %H:%M"),
                "attendees": [a for a in e["attendees"] if a != e.get("me")],
                "description": e.get("description", ""),
                "upcoming": e["date"] >= today, "file": d.display,
            })
    evs.sort(key=lambda e: (not e["upcoming"], e["start"] if e["upcoming"] else _neg(e["start"])))
    return evs


def _neg(s: str) -> str:
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def meeting_brief(docs: list[Doc], event_id: str, today: dt.date, context: dict) -> dict:
    event = None
    for d in docs:
        for e in d.events:
            if e["id"] == event_id:
                event = e
    if event is None:
        return {"error": "I couldn't find that meeting in the calendar files you've allowed."}
    return _brief(docs, event, today, context)


def _brief(docs: list[Doc], event: dict, today: dt.date, context: dict) -> dict:
    """Build a brief for a calendar event, or for a synthetic one (a person or a topic)."""
    roster = build_roster(docs)
    when = event["date"]
    ref = min(today, when) if when >= today else when
    attendees = [a for a in event["attendees"] if a != event.get("me")]
    people = {a.split()[0].lower() for a in attendees}
    for a in attendees:
        roster.add(a)

    frags = [f for f in build_frags(docs, roster) if f.date <= when]
    ix = Index(frags, roster)
    title_toks = [w for w in tokens(event.get("title", "")) if w not in GENERIC and w not in people]
    agenda_raw = re.sub(r"^\s*agenda\s*:\s*", "", event.get("description", ""), flags=re.I)
    agenda_items = [a.strip() for a in re.split(r",|;|\n|\band\b", agenda_raw) if a.strip()]
    agenda_toks = [w for w in tokens(agenda_raw) if w not in GENERIC and w not in people]
    topic = {w: 1.0 for w in title_toks}
    for w in agenda_toks:
        topic[w] = max(topic.get(w, 0), 0.8)
    one_to_one = len(people) == 1

    # how relevant is each line to this meeting?
    raw_topic = {f.id: ix.bm25(topic, f) for f in frags}
    mx = max(raw_topic.values(), default=0) or 1
    rel: dict[int, float] = {}
    for f in frags:
        s = 2.0 * raw_topic[f.id] / mx
        if f.people & people:
            s += 1.5
        doc_people = {p.split()[0].lower() for p in f.doc.people} | {
            w for w in tokens(f.doc.title) if w in roster.full}
        if doc_people & people:
            share = len(doc_people & people) / max(1, len(doc_people - {"me"}))
            s += 1.2 * min(1.0, share) + (1.0 if one_to_one and doc_people & people and
                                          any(w in people for w in tokens(f.doc.title)) else 0)
        age = _days(f.date, when)
        s += 0.3 * max(0.0, 1 - age / 60)
        rel[f.id] = s
    relevant = {fid for fid, s in rel.items() if s >= 1.1}

    sections = []

    # 1. last time you met
    last_doc, last_score = None, 0.0
    for d in docs:
        if d.kind not in ("note",) or d.date >= when:
            continue
        dp = {p.split()[0].lower() for p in d.people} | {w for w in tokens(d.title) if w in roster.full}
        s = len(dp & people) / max(1, len(people)) + 0.8 * len(set(tokens(d.title)) & set(title_toks))
        if one_to_one and not (dp & people):
            s = 0
        if s > last_score or (s == last_score and last_doc and d.date > last_doc.date and s > 0):
            last_doc, last_score = d, s
    if last_doc and last_score >= 0.5:
        lf = [f for f in frags if f.doc is last_doc and f.tags & {"decision", "action", "risk", "question"}][:4]
        sections.append({
            "id": "last", "title": f"Last time: {last_doc.title}, {fmt_date(last_doc.date)}",
            "subtitle": f"{_plural(_days(last_doc.date, when), 'day')} before this meeting",
            "items": [item(f, why=why_text(f)) for f in lf],
        })

    # 2. what changed
    changes = [c for c in find_changes(ix) if any(m.id in relevant for m in c["members"])]
    ch_items = []
    for c in changes[:5]:
        old, new = c["old"], c["new"]
        head = f"Changed: {c['reason']}" + (" (not final yet)" if c["tentative"] else "")
        ch_items.append({
            "text": new.text, "headline": head, "before": {"text": old.text, "source": src(old)},
            "source": src(new), "more_sources": [src(m) for m in c["members"] if m not in (old, new)],
            "why": f"Your notes from {fmt_date(old.date)} and {fmt_date(new.date)} talk about the same thing "
                   f"but say different things; the newer one is shown first. Check which is current.",
            "flags": ["changed"] + (["tentative"] if c["tentative"] else []), "confidence": "medium",
        })
    if ch_items:
        sections.append({"id": "changed", "title": "What's changed since it was agreed",
                         "subtitle": "Older notes may be out of date", "items": ch_items})
    changed_ids = {m.id for c in changes for m in c["members"]}

    # 3. open promises and actions
    threads = build_threads(ix, {"action", "question", "done"})
    act_items, q_items = [], []
    for t in threads:
        if not any(f.id in relevant for f in t.frags):
            continue
        status = thread_status(t)
        if status == "done":
            continue
        owner = thread_owner(t)
        due = thread_due(t)
        age = _days(t.first.date, ref)
        flags = []
        if due and due < ref:
            flags.append(f"overdue {_plural(_days(due, ref), 'day')}")
        elif due:
            flags.append(f"due {fmt_date(due)}")
        if len(t.frags) > 1:
            flags.append(f"written down {len(t.frags)} times")
        involved = (owner in people) or bool(set().union(*(f.people for f in t.frags)) & people)
        score = sum(rel[f.id] for f in t.frags) / len(t.frags) + 0.4 * (len(t.frags) - 1) + (
            1.0 if flags and flags[0].startswith("overdue") else 0) + (0.8 if owner == "you" and involved else 0)
        headline = None
        if t.kind == "action":
            who = roster.name(owner)
            headline = (f"You: open for {_plural(age, 'day')} (since {fmt_date(t.first.date)})" if owner == "you"
                        else f"{who}: open since {fmt_date(t.first.date)}")
            bucket = act_items
        else:
            headline = f"Unanswered since {fmt_date(t.first.date)}"
            bucket = q_items
        # your own promises and open questions: show where it started; anything else: the latest word on it
        show = (t.first if (owner == "you" and t.kind == "action") or t.kind == "question" else
                max(t.frags, key=lambda f: (len(f.toks) >= 3, f.date, f.id)))
        it = item(show, why=why_text(show, extra=(f"I linked {len(t.frags)} notes that talk about the same thing"
                                                  if len(t.frags) > 1 else "")),
                  flags=flags, extra_sources=t.frags, headline=headline,
                  confidence="high" if len(t.frags) > 1 or show.owner else "medium")
        it["owner"] = roster.name(owner)
        it["_score"] = score
        bucket.append(it)
    for bucket, sid, title, sub in (
            (act_items, "actions", "Open promises and actions", "Nothing in your notes says these are done"),
            (q_items, "questions", "Still unanswered", "Raised before, never answered in your notes")):
        bucket.sort(key=lambda x: -x.pop("_score"))
        if bucket:
            sections.append({"id": sid, "title": title, "subtitle": sub, "items": bucket[:6],
                             "more": max(0, len(bucket) - 6)})

    # 4. decisions on record
    dec = [f for f in frags if "decision" in f.tags and f.id in relevant and f.id not in changed_ids]
    dec.sort(key=lambda f: (-rel[f.id], f.date))
    if dec:
        sections.append({"id": "decisions", "title": "Decisions on record", "subtitle": "Nothing later contradicts these",
                         "items": [item(f, why=why_text(f), flags=(["not final"] if "tentative" in f.tags else []))
                                   for f in sorted(dec[:5], key=lambda f: f.date)]})

    # 5. half-written drafts that this meeting could finish
    drafts = _draft_gaps(docs, frags, ix, people, topic, roster)
    if drafts:
        sections.append({"id": "drafts", "title": "You started this but didn't finish",
                         "subtitle": "Your other notes may already have the missing parts", "items": drafts})

    # 6. links you saved
    expand = dict(topic)
    for f in sorted((f for f in frags if f.id in relevant and "link" not in f.tags), key=lambda f: -rel[f.id])[:8]:
        for w in f.toks:
            if w not in GENERIC and w not in roster.full and not w[0].isdigit():
                expand[w] = max(expand.get(w, 0), 0.35)
    links = [(ix.bm25(expand, f), f) for f in frags if "link" in f.tags]
    links = [x for x in links if x[0] > 1.0 and (set(x[1].toks) & set(topic) or
                                                 len(set(x[1].toks) & set(expand)) >= 2)]
    links.sort(key=lambda x: -x[0])
    if links:
        sections.append({"id": "links", "title": "Links you saved that look related",
                         "subtitle": "Shown, never opened - the assistant does not go online",
                         "items": [dict(item(f, why=why_text(f, _matched(expand, f))), url=f.url) for _, f in links[:3]]})

    # 7. honesty: what I couldn't check
    gaps = []
    if people and not any(s["id"] == "last" for s in sections):
        gaps.append({"text": f"I found no earlier meeting notes with {', '.join(roster.name(p) for p in sorted(people))}"
                             f"{' about this' if title_toks else ''}, so there's no “last time” to recap.",
                     "kind": "history"})
    for p in sorted(people):
        n = sum(1 for f in frags if p in f.people or p in {x.split()[0].lower() for x in f.doc.people})
        if n == 0:
            gaps.append({"text": f"I found nothing about {roster.name(p)} in your notes.", "kind": "person"})
        elif n <= 2:
            gaps.append({"text": f"Only {_plural(n, 'note')} mention {roster.name(p)}, so this brief may be thin on them.",
                         "kind": "person"})
    for a in agenda_items:
        at = [w for w in tokens(a) if w not in GENERIC]
        if at and not any(all(w in f.toks for w in at) for f in frags):
            gaps.append({"text": f"The agenda mentions “{a}” but I found nothing about it.", "kind": "agenda"})
    gaps += _unreadable_gaps(context, frags)
    used_guessed = sorted({f.doc.display for f in frags if f.date_guessed and f.id in relevant})
    if used_guessed:
        gaps.append({"text": f"No dates inside {', '.join(used_guessed)}, so I went by when the file was last "
                             f"changed. Treat the timing of those notes with care.", "kind": "dates"})
    if context.get("switched_off"):
        gaps.append({"text": f"You switched off {_plural(len(context['switched_off']), 'file')} "
                             f"({', '.join(context['switched_off'][:3])}), so I didn't look at them.", "kind": "scope"})
    sections.append({"id": "gaps", "title": "What I couldn't check", "subtitle": "So you know where this brief stops",
                     "items": gaps or [{"text": "Nothing obvious is missing. All the files you allowed were readable.",
                                        "kind": "ok"}], "plain": True})

    return {
        "meeting": {"title": event.get("title"),
                    "date_label": event.get("date_label") or (event["start"].strftime("%a ") + fmt_date(when)
                                                              + event["start"].strftime(", %H:%M")),
                    "attendees": attendees, "agenda": agenda_items},
        "talking_points": _talking_points(sections, roster, people),
        "sections": sections,
        "stats": {"lines_considered": len(frags), "lines_used": len(relevant)},
    }


def _matched(q: dict, f: Frag) -> list[str]:
    return [w for w in sorted(q, key=lambda w: -q[w]) if w in f.toks]


def _unreadable_gaps(context: dict, frags: list[Frag]) -> list[dict]:
    out = []
    for name in context.get("unreadable", []):
        stem_words = [w for w in tokens(re.sub(r"\d", " ", name)) if w not in ("png", "jpg", "jpeg")]
        refs = [f for f in frags if set(stem_words) & set(f.toks) or re.search(r"\b(screenshot|pic|photo|image)s?\b",
                                                                                 f.text, re.I)]
        extra = (f" Your note “{refs[0].text}” ({fmt_date(refs[0].date)}) points to it, so something "
                 f"relevant may be in it.") if refs else ""
        out.append({"text": f"I can't read images on this device yet, so I skipped {name}.{extra}",
                    "kind": "unreadable", "source": src(refs[0]) if refs else None})
    return out


_INCOMPLETE_RX = re.compile(r"(\bbecause|\band|\bbut|\bso|:|-|—|,)\s*$|\[?\btodo\b|\btbd\b|\bxx+\b|\[\s*\]|\?\?\?", re.I)


def _draft_gaps(docs, frags, ix: Index, people: set, topic: dict, roster: Roster) -> list[dict]:
    out = []
    pool = [f for f in frags if f.doc.kind not in ("draft", "links", "link")]
    for d in docs:
        if d.kind != "draft":
            continue
        dtoks = set(tokens(" ".join(d.lines)))
        recipient = None
        for ln in d.lines[:8]:
            m = re.match(r"^\s*(?:hi|hello|dear|hey)\s+(\w+)", ln, re.I)
            if m:
                recipient = m.group(1).lower()
        if not (dtoks & set(topic)) and not (dtoks & people) and recipient not in people:
            continue
        gaps = []
        used: set[int] = set()
        lines = d.lines
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s or i == 0 and s.lower().startswith("draft"):
                continue
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            empty_heading = s.endswith(":") and (not nxt or nxt.endswith(":") or nxt in ("-", "*"))
            if not (_INCOMPLETE_RX.search(s) or empty_heading) or re.match(r"^(hi|hello|dear|hey)\b", s, re.I):
                continue
            if s in ("-", "*"):
                continue
            label = re.sub(r"\[?\btodo\b[^\]]*\]?", "", s, flags=re.I).strip(" :[]-")
            want_risk = s.lower().rstrip().endswith("because") or label.lower().startswith("risk")
            want_money = bool(re.search(r"budget|number|cost|spend|price|£|\$|€", label, re.I))
            want_ask = label.lower().startswith("ask")
            q = {w: 1.0 for w in tokens(label) if w not in GENERIC and not w[0].isdigit()
                 and w not in MONTHS_AND_DAYS and (not want_risk or w not in SUBJECT_STOP)}
            scored_pool = []
            for f in pool:
                if f.id in used:
                    continue          # don't offer the same line for two gaps
                if want_risk and "risk" not in f.tags:
                    continue          # "...because" wants a reason, so look at risks/problems
                if want_money and not f.money:
                    continue
                sc = ix.bm25(q, f) if q else 0.0
                if want_risk:
                    sc += 1.0 + 0.5 * ix.bm25(topic, f)
                if want_ask and re.search(r"\bneeds?\b.*\bsign[ -]?off\b|\bapproval\b", f.text, re.I):
                    sc += 2.0
                if sc > 0:
                    scored_pool.append((sc, f))
            best, best_s = None, 0.0
            if scored_pool:
                top = max(sc for sc, _ in scored_pool)
                good = [(sc, f) for sc, f in scored_pool if sc >= (0.6 if want_money else 0.85) * top]
                best_s, best = max(good, key=lambda x: (x[1].date, x[0]) if want_money else (x[0], x[1].date))
            if best and best_s > 1.0:
                used.add(best.id)
                gaps.append({"line": s, "line_no": i + 1, "suggestion": item(best, why=why_text(
                    best, _matched(q, best), "the closest match in your other notes"), confidence="medium")})
        if gaps:
            out.append({
                "text": f"“{d.title}” is unfinished: {_plural(len(gaps), 'gap')} your notes may fill.",
                "headline": f"Draft from {fmt_date(d.date)}" + (f" to {roster.name(recipient)}" if recipient else ""),
                "source": {"path": d.path, "file": d.display, "title": d.title, "kind": d.kind, "line": 1,
                           "date": d.date.isoformat(), "date_label": fmt_date(d.date),
                           "date_guessed": d.date_source.startswith("file time")},
                "gaps": gaps, "why": "It's in your drafts and has empty or half-finished lines.",
                "flags": ["unfinished"], "confidence": "medium", "more_sources": [],
                "recipient": roster.name(recipient) if recipient else None,
            })
    return out


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _talking_points(sections: list[dict], roster: Roster, people: set) -> list[dict]:
    by_id = {s["id"]: s for s in sections}
    acts = by_id.get("actions", {}).get("items", [])
    mine = [{"text": f"Close the loop: “{it['text']}”", "source": it["source"],
             "why": f"{_cap(it['headline'].split(':', 1)[-1].strip())}, and nothing says it's done."}
            for it in acts if it.get("owner") == "You" and any(fl.startswith(("overdue", "written down"))
                                                                 for fl in it["flags"])]
    changed = [{"text": f"Confirm what's current: {it['headline'].replace('Changed: ', '')}"
                        f"{'' if 'tentative' not in it['flags'] else ''}",
                "source": it["source"], "why": "Your notes disagree with each other."}
               for it in by_id.get("changed", {}).get("items", [])]
    theirs = [{"text": f"Ask {it['owner']}: “{it['text']}”", "source": it["source"],
               "why": "It's theirs and still open in your notes."}
              for it in acts if it.get("owner") not in ("You", "unassigned") and it.get("owner", "").lower() in people]
    qs = [{"text": f"Get an answer: “{it['text']}”", "source": it["source"], "why": it["headline"] + "."}
          for it in by_id.get("questions", {}).get("items", [])]
    drafts = [{"text": f"Finish your update to {it['recipient']}: your notes can fill "
                       f"{_plural(len(it['gaps']), 'gap')}", "source": it["source"], "why": "It's still a draft."}
              for it in by_id.get("drafts", {}).get("items", [])
              if it.get("recipient") and it["recipient"].lower() in people]
    pts = mine[:2] + changed[:2] + theirs[:1] + drafts[:1] + qs[:1] + mine[2:3] + changed[2:3] + theirs[1:2]
    seen, out = set(), []
    for p in pts:
        if p["text"] not in seen:
            seen.add(p["text"])
            out.append(p)
    return out[:6]


# --------------------------------------------------------------------------
# Asking a question
# --------------------------------------------------------------------------
_MY_ACTIONS_RX = re.compile(r"\b(i owe|owe|waiting on me|my (?:actions|todos?|to-?dos|tasks)|what do i (?:need|have) to do|"
                            r"on my plate|did i promise|i promised|i forgot|forgetting)\b", re.I)
_CHANGED_RX = re.compile(r"\bwhat(?:'s| has| have)? changed\b|\bout of date\b|\bcontradict", re.I)
_Q_WORDS = re.compile(r"\b(what|whats|when|who|whom|where|why|how|did|do|does|we|i|the|is|are|was|were|about|"
                      r"tell|me|find|show|any|anything|there|regarding|re|handling|handles|handle|doing|happening|"
                      r"status|latest|current|currently|going|working|looking|responsible|dealing|sorting|"
                      r"managing|owns|owner|mean|means|happened|remind|recall|again|our|my|on|with|for|of)\b", re.I)


def _edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Damerau-Levenshtein (optimal string alignment) distance, capped at limit + 1."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _closest(word: str, vocab: dict, min_len: int = 5) -> str | None:
    """The word in `vocab` (word -> how common) that `word` is most likely a typo of.
    Short words are left alone: 'read' is a word, not a typo of 'real'."""
    if len(word) < min_len or not word.isalpha():
        return None
    limit = 1 if len(word) < 7 else 2
    best = None
    for v, n in vocab.items():
        if not v.isalpha() or v[0] != word[0] or abs(len(v) - len(word)) > limit:
            continue
        d = _edit_distance(word, v, limit)
        if d <= limit:
            key = (d, -n, v)
            if best is None or key < best[0]:
                best = (key, v)
    return best[1] if best else None


_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_WD_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_PERIOD_RX = re.compile(rf"\b(today|yesterday|this week|last week|this month|last month|"
                        rf"(?:in the |over the )?(?:past|last) (\d{{1,3}}) days|since ({_WD_ALT})|"
                        rf"in ({_MONTH_ALT}))\b", re.I)


def find_period(q: str, today: dt.date):
    """'this week', 'last month', 'in October'... -> (start, end, label, span) or None."""
    m = _PERIOD_RX.search(q)
    if not m:
        return None
    p = m.group(1).lower()
    one = dt.timedelta(days=1)
    if p == "today":
        a = b = today
        label = "today"
    elif p == "yesterday":
        a = b = today - one
        label = "yesterday"
    elif p == "this week":
        a, b, label = today - dt.timedelta(days=today.weekday()), today, "this week"
    elif p == "last week":
        a = today - dt.timedelta(days=today.weekday() + 7)
        b, label = a + dt.timedelta(days=6), "last week"
    elif p == "this month":
        a, b, label = today.replace(day=1), today, "this month"
    elif p == "last month":
        b = today.replace(day=1) - one
        a, label = b.replace(day=1), "last month"
    elif m.group(2):
        n = int(m.group(2))
        a, b, label = today - dt.timedelta(days=n), today, f"in the last {n} days"
    elif m.group(3):
        wd = WEEKDAYS[m.group(3).lower()]
        a = today - dt.timedelta(days=(today.weekday() - wd) % 7)
        b, label = today, f"since {a.strftime('%A')}"
    else:
        mon = MONTHS[m.group(4).lower()]
        y = today.year if mon <= today.month else today.year - 1
        a = dt.date(y, mon, 1)
        b = (dt.date(y + (mon == 12), mon % 12 + 1, 1)) - one
        label = f"in {a.strftime('%B')}"
    return a, b, label, m.span()


_KIND_WORDS = [("action", r"\b(actions?|to-?dos?|tasks?)\b"), ("risk", r"\b(risks?|problems?|issues?|blockers?)\b"),
               ("question", r"\b(open questions?|questions?)\b")]
_KIND_PLURAL = {"decision": "Decisions", "action": "Actions", "risk": "Risks", "question": "Open questions"}


def _kind_label(f: Frag) -> str:
    for tag, label in (("decision", "Decision"), ("done", "Done"), ("action", "Action"), ("risk", "Risk"),
                       ("question", "Open question")):
        if tag in f.tags:
            return label
    return "Note"


def ask(docs: list[Doc], question: str, today: dt.date, context: dict) -> dict:
    roster = build_roster(docs)
    frags = build_frags(docs, roster)
    ix = Index(frags, roster)
    q = question.strip()
    if not q:
        return {"status": "empty"}

    if _MY_ACTIONS_RX.search(q):
        threads = [t for t in build_threads(ix, {"action", "question", "done"})
                   if t.kind == "action" and thread_status(t) == "open" and thread_owner(t) == "you"]
        threads.sort(key=lambda t: t.first.date)
        items = []
        for t in threads[:8]:
            age = _days(t.first.date, today)
            due = thread_due(t)
            flags = [f"open {_plural(age, 'day')}"]
            if due and due < today:
                flags.insert(0, f"overdue {_plural(_days(due, today), 'day')}")
            if len(t.frags) > 1:
                flags.append(f"written down {len(t.frags)} times")
            show = t.first
            items.append(item(show, why=why_text(show, extra=(f"I linked {len(t.frags)} notes about the same thing"
                                                              if len(t.frags) > 1 else "")),
                              flags=flags, extra_sources=t.frags, headline=f"Since {fmt_date(t.first.date)}"))
        return {"status": "found" if items else "not_found", "kind": "my_actions",
                "summary": (f"{_plural(len(threads), 'thing')} you said you'd do that nothing in your notes "
                            f"marks as done. Oldest first:") if items else
                "I couldn't find anything you've promised that's still open.",
                "items": items, "gaps": _ask_gaps(context, frags)}

    if _CHANGED_RX.search(q):
        ch = find_changes(ix)
        items = [{"text": c["new"].text, "headline": f"Changed: {c['reason']}",
                  "before": {"text": c["old"].text, "source": src(c["old"])}, "source": src(c["new"]),
                  "more_sources": [], "why": "Two notes about the same thing disagree; newest shown first.",
                  "flags": ["changed"] + (["tentative"] if c["tentative"] else []), "confidence": "medium"}
                 for c in ch[:8]]
        return {"status": "found" if items else "not_found", "kind": "changes",
                "summary": "Things your notes say differently over time, newest first:" if items else
                "I didn't find notes that contradict each other.", "items": items, "gaps": _ask_gaps(context, frags)}

    # "what happened last week?" / "decisions in October"
    period = find_period(q, today)
    qx = q if not period else (q[:period[3][0]] + " " + q[period[3][1]:])
    in_period = (lambda f: period[0] <= f.date <= period[1]) if period else (lambda f: True)
    plabel = f"{period[2]} ({fmt_date(period[0])}" + (f" to {fmt_date(period[1])})" if period[1] != period[0] else ")") \
        if period else ""

    intent = ("decision" if re.search(r"\b(decid\w*|decision\w*|agree\w*|go with|choose|chose)\b", qx, re.I) else
              "when" if re.search(r"\bwhen\b|\bdate\b|\bdeadline\b", qx, re.I) else
              "amount" if re.search(r"\b(how much|budget|cost|costs|price|pricing|spend)\b|[£$€]", qx, re.I) else
              "who" if re.search(r"\bwho\b", qx, re.I) else
              "link" if re.search(r"\b(link|article|url|saved|bookmark)\b", qx, re.I) else "")
    content = _Q_WORDS.sub(" ", qx)
    if intent == "decision":   # "did we agree on SSO" is about SSO, not about agreeing
        content = re.sub(r"\b(decid\w*|decision\w*|agree\w*|go with|choose|chose)\b", " ", content, flags=re.I)
    only = "decision" if intent == "decision" else None
    if period:                 # "actions since Monday", "risks last week": a filter, not a search word
        for kind, rx in _KIND_WORDS:
            if re.search(rx, content, re.I):
                only = only or kind
                content = re.sub(rx, " ", content, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z0-9£$€']+", content)
             if tokens(w) and tokens(w)[0] not in GENERIC]
    specific = [w for w in tokens(content) if w not in GENERIC]

    if period and not specific:
        return _period_overview(frags, period, plabel, context, only=only)

    qt = specific or tokens(content)
    shown = {tokens(w)[0]: w.lower().removesuffix("'s") for w in words}
    # forgive spelling mistakes: a word that's nowhere in your notes but one letter
    # off a word that is ("budjet" -> "budget", "prya" -> "priya")
    query: dict[str, float] = {}
    corrections = []
    for w in qt:
        c = None if ix.df.get(w) else _closest(w, ix.df)
        if c and c not in query and c not in qt:
            corrections.append((shown.get(w, w), c))
            shown[c] = c
            query[c] = 1.0
        else:
            query[w] = 1.0
    qt = list(query)
    note = ("I read " + ", ".join(f"“{a}” as “{b}”" for a, b in corrections) + ". ") \
        if corrections else ""
    if not intent and {"budget", "pricing"} & set(query):
        intent = "amount"          # e.g. "what's the budjet?" once the spelling is fixed
    scored = []
    for f in frags:
        if not in_period(f):
            continue
        s = ix.bm25(query, f)
        if s <= 0:
            continue
        if intent == "decision" and "decision" in f.tags:
            s *= 1.6
        if intent == "when" and f.dates:
            s *= 1.3
        if intent == "amount" and f.money:
            s *= 1.5
        if intent == "link" and "link" in f.tags:
            s *= 1.6
        if intent == "who" and (f.owner or f.people):
            s *= 1.2
        if intent != "link" and "link" in f.tags:
            s *= 0.6
        if f.doc.kind == "draft":
            s *= 0.5          # your unsent drafts aren't a record of what was agreed
        if re.search(r"\btodo\b|\[\s*\]\s*$|\btbd\b", f.text, re.I):
            s *= 0.4
        s *= 1 + 0.15 * max(0.0, 1 - _days(f.date, today) / 90)
        scored.append((s, f))
    scored.sort(key=lambda x: -x[0])
    total_w = sum(ix.weight(w) for w in query) or 1
    gaps = _ask_gaps(context, frags)
    missing = [w for w in query if not ix.df.get(w)]
    missing_share = sum(ix.weight(w) for w in missing) / total_w
    if not scored:
        if period:
            w = ", ".join(f"“{shown.get(x, x)}”" for x in qt[:4]) or "that"
            return {"status": "not_found", "summary": note + f"I couldn't find anything about {w} in notes dated "
                                                             f"{plabel}.", "items": [], "gaps": gaps, "query_words": qt}
        return {"status": "not_found", "summary": note + _not_found_text([shown.get(w, w) for w in qt], frags),
                "items": [], "gaps": gaps, "query_words": qt}
    top_s, top = scored[0]
    coverage = sum(ix.weight(w) for w in query if w in top.toks) / total_w
    known_w = sum(ix.weight(w) for w in query if w not in missing) or 1
    known_cov = sum(ix.weight(w) for w in query if w in top.toks) / known_w
    # most of the question isn't in your notes at all -> say so rather than answer the leftover word
    if missing and (missing_share >= 0.5 or (missing_share >= 0.3 and known_cov < 0.8)):
        near = [item(f, why=why_text(f, [shown.get(w, w) for w in _matched(query, f)]), confidence="low")
                for _, f in scored[:3]]
        miss = ", ".join(f"“{shown.get(w, w)}”" for w in missing)
        return {"status": "not_found", "summary": note + f"I couldn't find anything about {miss} in your notes, "
                                                         f"so I can't answer that. These lines share some words "
                                                         f"with your question but don't answer it:",
                "items": near, "gaps": gaps, "query_words": qt}
    if coverage < 0.34 and not (missing and known_cov >= 0.8):
        near = [item(f, why=why_text(f, [shown.get(w, w) for w in _matched(query, f)]), confidence="low")
                for _, f in scored[:3]]
        return {"status": "unsure", "summary": note + "I'm not sure. Nothing in your notes clearly answers that. "
                                                      "The closest lines only partly match:",
                "items": near, "gaps": gaps, "query_words": qt}
    keep = [f for s, f in scored if s >= 0.45 * top_s][:10]
    # group into threads so the history reads in order
    groups: list[list[Frag]] = []
    for f in keep:
        for g in groups:
            if max(ix.sim(f, h) for h in g) >= 0.3:
                g.append(f)
                break
        else:
            groups.append([f])
    main = sorted((f for f in groups[0] if "link" not in f.tags or intent == "link"), key=lambda f: (f.date, f.id))
    main = main or groups[0]
    latest = main[-1]
    if intent == "decision":
        decs = [(s, f) for s, f in scored if "decision" in f.tags]
        if decs:
            best_d = decs[0][0]
            close = [f for s, f in decs if s >= 0.5 * best_d]
            latest = max(close, key=lambda f: (bool(re.match(r"\s*decision\b", f.text, re.I)), f.date, f.id))
            main = sorted({f.id: f for f in main + [x for x in close if x is not latest]}.values(),
                          key=lambda f: (f.date, f.id))
    qset = set(query)
    has_money = bool(re.search(r"[£$€]|\d+k\b", q, re.I))
    has_date = bool(find_dates(q, today))

    def change_fits(c):
        if not (c["subject"] & qset) or not any(m in keep for m in c["members"]):
            return False
        if c["kind"] == "money":
            return intent == "amount" or has_money
        if c["kind"] == "date":
            return intent == "when" or has_date or bool(qset & {w for w in c["subject"] if w not in ix.ent})
        return True
    changes = [c for c in find_changes(ix) if change_fits(c)]
    if changes:
        c = changes[0]
        latest = c["new"]
        main = sorted({f.id: f for f in main + [c["old"]]}.values(), key=lambda f: (f.date, f.id))
    conf = "high" if coverage >= 0.66 else "medium"
    mt = lambda f: [shown.get(w, w) for w in _matched(query, f)]  # noqa: E731
    items = [item(latest, why=why_text(latest, mt(latest)), headline="Most recent answer in your notes",
                  confidence=conf, flags=(["not final"] if "tentative" in latest.tags else []))]
    history = [f for f in main if f is not latest and f.date <= latest.date]
    for f in reversed(history[-4:]):
        items.append(item(f, why=why_text(f, mt(f)), headline="Earlier", confidence="medium"))
    used = {id(x) for x in [latest] + history}
    related = [f for g in groups for f in g if id(f) not in used][:3]
    for f in related:
        items.append(item(f, why=why_text(f, mt(f)), headline="Also related", confidence="medium"))
    summary = "Here's what your notes say, newest first."
    if changes:
        c = changes[0]
        summary = (f"Heads up: this changed ({c['reason']}). Your notes from {fmt_date(c['old'].date)} and "
                   f"{fmt_date(c['new'].date)} disagree; the newest is first.")
        if c["tentative"]:
            summary += " It isn't final yet."
    if missing:
        summary += f" (Nothing in your notes mentions {', '.join(chr(8220) + shown.get(w, w) + chr(8221) for w in missing)}.)"
    if period:
        summary += f" Only notes dated {plabel}."
    return {"status": "found", "summary": note + summary, "items": items, "gaps": gaps, "query_words": qt,
            "confidence": conf}


def _period_overview(frags: list[Frag], period, plabel: str, context: dict, only: str | None = None) -> dict:
    """'What happened last week?': everything your notes recorded in that window, newest first.
    'Decisions in October': just the decisions."""
    a, b = period[0], period[1]
    inside = [f for f in frags if a <= f.date <= b and "link" not in f.tags and (only is None or only in f.tags)]
    inside.sort(key=lambda f: (-f.date.toordinal(), not (f.tags - {"tentative"}), f.id))
    items = [item(f, why=why_text(f), headline=f"{fmt_date(f.date)} · {_kind_label(f)}",
                  flags=(["not final"] if "tentative" in f.tags else []), confidence="high") for f in inside[:12]]
    guessed = sorted({f.doc.display for f in inside if f.date_guessed})
    gaps = _ask_gaps(context, frags)
    if guessed:
        gaps.append({"text": f"No dates inside {', '.join(guessed)}, so they're placed by when the file was last "
                             f"changed.", "kind": "dates"})
    what = _KIND_PLURAL[only].lower() if only else "anything"
    if not items:
        return {"status": "not_found", "kind": "period", "items": [], "gaps": gaps,
                "summary": f"I found no {what} in your notes dated {plabel}."}
    more = f" Showing the newest 12 of {len(inside)}." if len(inside) > 12 else ""
    lead = f"{_KIND_PLURAL[only]} your notes recorded" if only else "Here's what your notes recorded"
    return {"status": "found", "kind": "period", "items": items, "gaps": gaps,
            "summary": f"{lead} {plabel}, newest first.{more}"}


def _not_found_text(words, frags) -> str:
    w = ", ".join(f"“{x}”" for x in words[:4]) or "that"
    files = len({f.doc.path for f in frags})
    return f"I couldn't find anything about {w} in the {_plural(files, 'file')} you've let me see."


def _ask_gaps(context: dict, frags: list[Frag]) -> list[dict]:
    g = []
    if context.get("switched_off"):
        g.append({"text": f"Not searched: {_plural(len(context['switched_off']), 'file')} you switched off.",
                  "kind": "scope"})
    if context.get("unreadable"):
        g.append({"text": f"Not searched: {_plural(len(context['unreadable']), 'image')} I can't read yet "
                          f"({', '.join(context['unreadable'][:2])}).", "kind": "unreadable"})
    return g


# --------------------------------------------------------------------------
# Chat: one message in, the right kind of help out
# --------------------------------------------------------------------------
_HELLO_RX = re.compile(r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|thanks|thank you|cheers)\b[\s!.,]*$",
                       re.I)
_HELP_RX = re.compile(r"^\s*(help|\?|what can you do|what do you do|how do (i|you) (use|work)|commands|"
                      r"what can i ask)\b", re.I)
_MEETING_RX = re.compile(r"\b(prep(are)?( me)?( for)?|brief( me)?( for| on)?|get ready|ready for|next meeting|"
                         r"my meeting|meeting with|before (my|the) (meeting|1:1|call|steering))\b", re.I)
_ABOUT_RX = re.compile(r"\b(?:who is|who's|whos|what do i know about|tell me about|anything (?:on|about)|"
                       r"catch me up on|update me on|update on|status of|what'?s (?:going on|happening|the latest) "
                       r"(?:with|on)|summari[sz]e|everything (?:on|about)|remind me about)\s+(.+?)[?.!]*$", re.I)

CHAT_SUGGESTIONS = ["Prepare me for my next meeting", "What do I owe people?", "What has changed?",
                    "Catch me up on data residency", "Tell me about Dana", "When is the launch?"]


def _events(docs):
    return [e for d in docs for e in d.events]


def _match_event(docs, msg: str, today: dt.date, roster: Roster) -> dict | None:
    evs = _events(docs)
    if not evs:
        return None
    upcoming = sorted((e for e in evs if e["date"] >= today), key=lambda e: e["start"])
    if re.search(r"\bnext (meeting|call)\b|\bmy next\b", msg, re.I) and upcoming:
        return upcoming[0]
    mt = set(tokens(msg))
    names = {f for f in roster.full if re.search(rf"\b{f}\b", msg, re.I)}
    one_to_one = bool(re.search(r"\b1\s*[:\-]\s*1\b|\bone[ -]?(on|to)[ -]?one\b", msg, re.I))
    best, best_s = None, 0.0
    for e in evs:
        others = [a for a in e["attendees"] if a != e.get("me")]
        firsts = {a.split()[0].lower() for a in others}
        tt = {w for w in tokens(e.get("title", "")) if w not in GENERIC}
        s = 2.0 * len(mt & tt) + 1.5 * len(names & firsts)
        if one_to_one and len(others) == 1 and names & firsts:
            s += 1.5
        if s <= 0:
            continue
        s += 0.5 if e["date"] >= today else 0      # prefer the coming meeting over a past one
        s -= 0.002 * abs((e["date"] - today).days)
        if s > best_s:
            best, best_s = e, s
    return best


def _answer(r: dict) -> dict:
    r = dict(r)
    r["answer_kind"] = r.pop("kind", "question")
    return {"kind": "answer", **r}


def _synthetic(title: str, attendees: list[str], today: dt.date, label: str) -> dict:
    start = dt.datetime.combine(today, dt.time(23, 59))
    return {"id": "chat", "title": title, "attendees": attendees, "me": None, "description": "",
            "date": today, "start": start, "date_label": label}


def _fix_names(msg: str, roster: Roster, docs: list[Doc]) -> tuple[str, list[tuple[str, str]]]:
    """'prepare me for my 1:1 with prya' -> 'Priya'. Only words that appear nowhere in
    your notes are corrected, so real words ('data') are never turned into names ('Dana')."""
    vocab = set(tokens(" ".join(ln for d in docs for ln in d.lines if d.kind != "calendar")))
    names = {f: 1 for f in roster.full}
    fixes: list[tuple[str, str]] = []

    def rep(m):
        w = m.group(0)
        lw = w.lower()
        if len(lw) < 4 or lw in names or lw in STOP or lw in GENERIC or lw in vocab or stem(lw) in vocab:
            return w
        c = _closest(lw, names, 4)
        if not c:
            return w
        fixes.append((w, roster.name(c)))
        return roster.name(c)

    return re.sub(r"[A-Za-z]+", rep, msg), fixes


def chat(docs: list[Doc], message: str, today: dt.date, context: dict) -> dict:
    """Route one chat message to the right kind of help. Stateless: nothing about the
    conversation is kept here; the browser holds the conversation, in page memory only."""
    msg = (message or "").strip()[:500]
    if not msg:
        return {"kind": "text", "text": "Ask me anything about the notes you've allowed.",
                "suggestions": CHAT_SUGGESTIONS}
    roster = build_roster(docs)
    msg, fixes = _fix_names(msg, roster, docs)
    r = _chat(docs, msg, today, context, roster)
    if fixes:
        note = "I read " + ", ".join(f"“{a}” as {b}" for a, b in fixes) + ". "
        key = "summary" if r.get("kind") == "answer" else "text"
        r[key] = note + (r.get(key) or "")
    return r


def _chat(docs: list[Doc], msg: str, today: dt.date, context: dict, roster: Roster) -> dict:
    files = len({d.path for d in docs})
    if _HELLO_RX.match(msg):
        return {"kind": "text", "suggestions": CHAT_SUGGESTIONS,
                "text": f"Hi! I can see {_plural(files, 'file')} you've allowed. I only read them when you ask, "
                        f"and I keep nothing afterwards. What would you like to know?"}
    if _HELP_RX.match(msg):
        return {"kind": "help", "suggestions": CHAT_SUGGESTIONS, "text": "Here's what you can ask me:",
                "lines": [
                    "Prepare for a meeting: “prepare me for my 1:1 with Priya”, “brief me for "
                    "steering”, “prepare me for my next meeting”.",
                    "Catch up on a person or topic: “tell me about Dana”, “catch me up on data "
                    "residency”.",
                    "Ask a question: “when is the launch?”, “what did we decide about the vendor?”.",
                    "Find what you've forgotten: “what do I owe people?”, “what has changed?”.",
                    "Every answer quotes your notes with the file and line. If something isn't in your notes, "
                    "I'll say so instead of guessing.",
                ]}

    # 1. preparing for a meeting
    if _MEETING_RX.search(msg):
        ev = _match_event(docs, msg, today, roster)
        if ev:
            b = _brief(docs, ev, today, context)
            return {"kind": "brief", "brief": b,
                    "text": f"Here's your brief for “{ev.get('title')}” ({b['meeting']['date_label']})."}
        upcoming = sorted((e for e in _events(docs) if e["date"] >= today), key=lambda e: e["start"])
        if upcoming:
            return {"kind": "text", "text": "I couldn't tell which meeting you mean. These are coming up in "
                                            "your calendar:",
                    "suggestions": [f"Prepare me for {e.get('title')}" for e in upcoming[:5]]}

    # 2. catching up on a person or a topic
    m = _ABOUT_RX.search(msg)
    subject = m.group(1).strip() if m else ""
    bare = msg.strip(" ?.!").lower()
    if not subject and bare in roster.full:
        subject = bare
    if subject:
        subject = re.sub(r"^(the|our|my)\s+", "", subject, flags=re.I)
        words = subject.split()
        first = re.sub(r"'s$", "", words[0].lower()) if words else ""
        if first in roster.full and len(words) <= 2:
            full = roster.full[first]
            b = _brief(docs, _synthetic(f"Catch-up: {full}", [full], today,
                                        "Everything your notes say, as of today"), today, context)
            if b["stats"]["lines_used"]:
                return {"kind": "brief", "brief": b, "text": f"Here's what your notes say about {full}."}
            return _answer(ask(docs, subject, today, context))
        if [w for w in tokens(subject) if w not in GENERIC]:
            b = _brief(docs, _synthetic(subject[:1].upper() + subject[1:], [], today,
                                        "Everything your notes say, as of today"), today, context)
            useful = [s for s in b["sections"] if s["id"] != "gaps" and s.get("items")]
            if useful:
                return {"kind": "brief", "brief": b, "text": f"Here's what your notes say about {subject}."}
            return _answer(ask(docs, subject, today, context))

    # 3. everything else: a direct question
    return _answer(ask(docs, msg, today, context))
