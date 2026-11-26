"""Explainable, data-driven study insights (no opaque ML or external services)."""
from __future__ import annotations
from datetime import date, timedelta
from collections import defaultdict
from typing import Iterable
from .models import Session


def build_insights(sessions: Iterable[Session], today: date | None = None) -> list[dict[str, str]]:
    """Return transparent, supportive observations from the user's own logged data."""
    rows = list(sessions)
    today = today or date.today()
    if not rows:
        return [{"kind": "welcome", "title": "Start with one entry", "detail":
                 "Log a session to unlock trends. Keep sessions and breaks flexible."}]
    by_subject: dict[str, int] = defaultdict(int)
    for s in rows:
        by_subject[s.subject] += s.focused_minutes
    top = sorted(by_subject.items(), key=lambda x: (-x[1], x[0]))[0]
    recent_start = today - timedelta(days=6)
    recent = [s for s in rows if recent_start <= date.fromisoformat(s.date) <= today]
    insights = [{"kind": "subject", "title": f"Most logged subject: {top[0]}",
                 "detail": f"{top[1]} minutes recorded. This describes your log, not a measure of mastery."}]
    if recent:
        avg = round(sum(s.focused_minutes for s in recent) / len(recent))
        insights.append({"kind": "recent", "title": "Recent session pattern",
                        "detail": f"{len(recent)} session(s) in the last 7 days, averaging {avg} minutes. Consider what session length felt sustainable."})
    subjects_recent = {s.subject for s in recent}
    not_recent = sorted(set(by_subject) - subjects_recent)
    if not_recent:
        insights.append({"kind": "coverage", "title": "Subjects not recently logged",
                        "detail": "You haven't logged these recently: " + ", ".join(not_recent[:5]) + ". If relevant, consider a short review, with breaks."})
    return insights
