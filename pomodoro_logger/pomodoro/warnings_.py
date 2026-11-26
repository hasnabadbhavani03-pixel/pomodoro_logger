"""Threshold warning indicators (stretch feature)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from .logic import daily_totals
from .models import DEFAULT_SETTINGS, Session

LEVELS = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


@dataclass
class Warn:
    level: str      # CRITICAL | WARNING | INFO
    code: str       # machine-readable tag
    message: str


def get_warnings(sessions: Iterable[Session], today: date | None = None,
                 settings: dict | None = None) -> list[Warn]:
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    today = today or date.today()
    sessions = list(sessions)
    out: list[Warn] = []
    if not sessions:
        return [Warn("INFO", "NO_DATA", "No sessions logged yet.")]

    totals = daily_totals(sessions)

    # 1. Critical limit breaches: too many focused minutes in a single day
    for d, m in sorted(totals.items(), reverse=True):
        if m > cfg["daily_limit"]:
            out.append(Warn("CRITICAL", "DAILY_LIMIT",
                            f"{d}: {m} min logged in one day exceeds the {cfg['daily_limit']} min limit."))

    # 2. Anomalous individual entries
    for s in sessions:
        if s.focused_minutes >= cfg["anomaly_session"]:
            out.append(Warn("WARNING", "LONG_SESSION",
                            f"#{s.id} {s.date} {s.subject}: single session of {s.focused_minutes} min is unusually long."))
        elif s.focused_minutes < 5:
            out.append(Warn("INFO", "SHORT_SESSION",
                            f"#{s.id} {s.date} {s.subject}: only {s.focused_minutes} min - was this intentional?"))
        if s.pomodoros >= 2 and s.focused_minutes / s.pomodoros < 10:
            out.append(Warn("WARNING", "RATIO",
                            f"#{s.id} {s.date} {s.subject}: {s.pomodoros} pomodoros in {s.focused_minutes} min looks inconsistent."))
        if s.break_minutes > s.focused_minutes:
            out.append(Warn("INFO", "BREAKS",
                            f"#{s.id} {s.date} {s.subject}: breaks ({s.break_minutes} min) exceed focus time."))

    # 3. Probable duplicate entries
    keys = Counter((s.date, s.subject, s.focused_minutes, s.notes) for s in sessions)
    for (d, subj, mins, _), n in keys.items():
        if n > 1:
            out.append(Warn("WARNING", "DUPLICATE",
                            f"{n} identical entries on {d} for {subj} ({mins} min) - possible double entry."))

    # 4. Inactivity / overdue study
    last = max(datetime.strptime(d, "%Y-%m-%d").date() for d in totals)
    gap = (today - last).days
    if gap >= cfg["inactive_days"]:
        out.append(Warn("WARNING", "INACTIVE",
                        f"No study logged for {gap} days (last session {last.isoformat()})."))

    # 5. Goal shortfalls (recent days)
    window = [today - timedelta(days=i) for i in range(7)]
    short = [d for d in window if totals.get(d.isoformat(), 0) < cfg["daily_goal"]]
    if len(short) >= 4:
        out.append(Warn("INFO", "GOAL_SHORTFALL",
                        f"{len(short)} of the last 7 days were below the {cfg['daily_goal']} min daily goal."))
    if totals.get(today.isoformat(), 0) < cfg["daily_goal"]:
        out.append(Warn("INFO", "TODAY_GOAL",
                        f"Today: {totals.get(today.isoformat(), 0)} of {cfg['daily_goal']} min goal."))

    out.sort(key=lambda w: LEVELS[w.level])
    return out
