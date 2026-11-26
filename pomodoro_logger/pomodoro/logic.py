"""Core business logic: record sessions, search/filter, aggregate by subject."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from .models import Session
from .storage import Storage
from .validation import validate_session_fields, ValidationError


def record_session(storage: Storage, raw: dict, today: date | None = None) -> Session:
    """Validate raw user input and persist it. Raises ValidationError."""
    clean = validate_session_fields(raw, today)
    return storage.add(clean)


# ------------------------------------------------------------------- search
SORT_KEYS = {
    "date": lambda s: (s.date, s.id),
    "subject": lambda s: (s.subject.lower(), s.date),
    "minutes": lambda s: (s.focused_minutes, s.date),
    "pomodoros": lambda s: (s.pomodoros, s.date),
    "id": lambda s: s.id,
}


def search(sessions: Iterable[Session], keyword: str = "", subject: str = "",
           date_from: str | None = None, date_to: str | None = None,
           min_minutes: int | None = None, max_minutes: int | None = None,
           sort_by: str = "date", descending: bool = True) -> list[Session]:
    """Keyword + category filtering. All filters are optional and ANDed.

    * ``keyword``  - case-insensitive substring in subject OR notes
    * ``subject``  - case-insensitive substring match on the subject (category)
    """
    kw, subj = keyword.strip().lower(), subject.strip().lower()
    out = []
    for s in sessions:
        if kw and kw not in s.subject.lower() and kw not in s.notes.lower():
            continue
        if subj and subj not in s.subject.lower():
            continue
        if date_from and s.date < date_from:
            continue
        if date_to and s.date > date_to:
            continue
        if min_minutes is not None and s.focused_minutes < min_minutes:
            continue
        if max_minutes is not None and s.focused_minutes > max_minutes:
            continue
        out.append(s)
    key = SORT_KEYS.get(sort_by, SORT_KEYS["date"])
    return sorted(out, key=key, reverse=descending)


# -------------------------------------------------------------- aggregation
def minutes_by_subject(sessions: Iterable[Session]) -> list[dict]:
    """Summarise focused minutes per subject (the heart of the brief)."""
    agg: dict[str, dict] = defaultdict(lambda: {"minutes": 0, "sessions": 0, "pomodoros": 0})
    for s in sessions:
        a = agg[s.subject]
        a["minutes"] += s.focused_minutes
        a["sessions"] += 1
        a["pomodoros"] += s.pomodoros
    total = sum(a["minutes"] for a in agg.values()) or 1
    rows = [{"subject": k, **v,
             "avg_session": round(v["minutes"] / v["sessions"], 1),
             "share": round(100 * v["minutes"] / total, 1)}
            for k, v in agg.items()]
    return sorted(rows, key=lambda r: (-r["minutes"], r["subject"]))


def daily_totals(sessions: Iterable[Session]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for s in sessions:
        totals[s.date] += s.focused_minutes
    return dict(sorted(totals.items()))


def weekly_totals(sessions: Iterable[Session]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for s in sessions:
        y, w, _ = datetime.strptime(s.date, "%Y-%m-%d").isocalendar()
        totals[f"{y}-W{w:02d}"] += s.focused_minutes
    return dict(sorted(totals.items()))


def subjects(sessions: Iterable[Session]) -> list[str]:
    return sorted({s.subject for s in sessions})


def fmt_minutes(minutes: float) -> str:
    """90 -> '1h 30m'."""
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"
