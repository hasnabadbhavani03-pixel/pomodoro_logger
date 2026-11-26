"""Executive summary: totals, averages, status indicator, key trends."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from .logic import minutes_by_subject, daily_totals
from .models import DEFAULT_SETTINGS, Session


def _d(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def current_streak(day_set: set[date], today: date) -> int:
    """Consecutive study days ending today (or yesterday, if today is empty)."""
    cursor = today if today in day_set else today - timedelta(days=1)
    n = 0
    while cursor in day_set:
        n += 1
        cursor -= timedelta(days=1)
    return n


def longest_streak(day_set: set[date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(day_set):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def build_summary(sessions: Iterable[Session], today: date | None = None,
                  daily_goal: int = DEFAULT_SETTINGS["daily_goal"]) -> dict:
    sessions = list(sessions)
    today = today or date.today()
    out: dict = {"as_of": today.isoformat(), "daily_goal": daily_goal,
                 "total_sessions": len(sessions)}
    if not sessions:
        out.update(total_minutes=0, total_pomodoros=0, active_days=0, avg_session=0,
                   avg_per_active_day=0, longest_session=None, best_day=None,
                   top_subject=None, by_subject=[], current_streak=0,
                   longest_streak=0, last7=0, prev7=0, trend="No data yet",
                   trend_pct=None, avg_daily_last7=0, status="NO DATA",
                   status_detail="Log your first session to see insights.",
                   first_date=None, last_date=None, today_minutes=0)
        return out

    totals = daily_totals(sessions)
    day_set = {_d(k) for k in totals}
    total_min = sum(s.focused_minutes for s in sessions)
    by_subject = minutes_by_subject(sessions)
    longest = max(sessions, key=lambda s: (s.focused_minutes, s.date))
    best_day = max(totals.items(), key=lambda kv: (kv[1], kv[0]))

    def window(start_offset: int, end_offset: int) -> int:
        lo, hi = today - timedelta(days=start_offset), today - timedelta(days=end_offset)
        return sum(m for d, m in totals.items() if lo <= _d(d) <= hi)

    last7, prev7 = window(6, 0), window(13, 7)
    if prev7 == 0 and last7 == 0:
        trend, pct = "No activity in the last 14 days", None
    elif prev7 == 0:
        trend, pct = "Improving ▲ (new activity this week)", None
    else:
        pct = round(100 * (last7 - prev7) / prev7, 1)
        if pct >= 10:
            trend = f"Improving ▲ (+{pct}% vs previous 7 days)"
        elif pct <= -10:
            trend = f"Declining ▼ ({pct}% vs previous 7 days)"
        else:
            trend = f"Steady ■ ({pct:+}% vs previous 7 days)"

    avg7 = round(last7 / 7, 1)
    if last7 == 0:
        status, detail = "INACTIVE", "No study logged in the last 7 days."
    elif avg7 >= daily_goal:
        status, detail = "ON TRACK", f"Averaging {avg7} min/day (goal {daily_goal})."
    elif avg7 >= 0.6 * daily_goal:
        status, detail = "NEEDS FOCUS", f"Averaging {avg7} min/day - below the {daily_goal} min goal."
    else:
        status, detail = "BEHIND", f"Averaging only {avg7} min/day vs a {daily_goal} min goal."

    out.update(
        total_minutes=total_min,
        total_pomodoros=sum(s.pomodoros for s in sessions),
        active_days=len(day_set),
        avg_session=round(total_min / len(sessions), 1),
        avg_per_active_day=round(total_min / len(day_set), 1),
        longest_session={"minutes": longest.focused_minutes, "subject": longest.subject,
                         "date": longest.date},
        best_day={"date": best_day[0], "minutes": best_day[1]},
        top_subject=by_subject[0],
        by_subject=by_subject,
        current_streak=current_streak(day_set, today),
        longest_streak=longest_streak(day_set),
        last7=last7, prev7=prev7, trend=trend, trend_pct=pct,
        avg_daily_last7=avg7, status=status, status_detail=detail,
        first_date=min(totals), last_date=max(totals),
        today_minutes=totals.get(today.isoformat(), 0),
    )
    return out
