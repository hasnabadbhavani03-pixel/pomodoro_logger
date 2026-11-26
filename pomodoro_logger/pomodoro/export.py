"""Multi-format export: Markdown, plain-text audit log, CSV, optional chart."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from . import APP_NAME
from .logic import daily_totals, fmt_minutes, minutes_by_subject
from .models import SESSION_FIELDS, Session
from .summary import build_summary
from .warnings_ import Warn, get_warnings


# ------------------------------------------------------------------ renderers
def render_markdown(sessions: list[Session], summary: dict, warns: list[Warn]) -> str:
    L = [f"# {APP_NAME} - Report", "",
         f"_Generated {datetime.now():%Y-%m-%d %H:%M} | data as of {summary['as_of']}_", "",
         "## Executive Summary", "",
         "| Metric | Value |", "|---|---|",
         f"| Total sessions | {summary['total_sessions']} |",
         f"| Total focused time | {fmt_minutes(summary['total_minutes'])} ({summary['total_minutes']} min) |",
         f"| Total pomodoros | {summary['total_pomodoros']} |",
         f"| Active study days | {summary['active_days']} |",
         f"| Average session | {summary['avg_session']} min |",
         f"| Average per active day | {summary['avg_per_active_day']} min |"]
    if summary["top_subject"]:
        ts = summary["top_subject"]
        L.append(f"| Top subject | {ts['subject']} ({ts['minutes']} min, {ts['share']}%) |")
        ls = summary["longest_session"]
        L.append(f"| Longest session | {ls['minutes']} min - {ls['subject']} on {ls['date']} |")
    L += [f"| Current streak | {summary['current_streak']} day(s) |",
          f"| Longest streak | {summary['longest_streak']} day(s) |",
          f"| Last 7 days vs previous 7 | {summary['last7']} vs {summary['prev7']} min |",
          f"| Trend | {summary['trend']} |",
          f"| Status | **{summary['status']}** - {summary['status_detail']} |", "",
          "## Focused Minutes by Subject", "",
          "| Subject | Minutes | Sessions | Pomodoros | Avg/session | Share |",
          "|---|---:|---:|---:|---:|---:|"]
    for r in summary["by_subject"]:
        L.append(f"| {r['subject']} | {r['minutes']} | {r['sessions']} | {r['pomodoros']} "
                 f"| {r['avg_session']} | {r['share']}% |")
    L += ["", "## Warnings", ""]
    L += [f"- **{w.level}** `{w.code}` - {w.message}" for w in warns] or ["- None"]
    L += ["", "## All Sessions", "",
          "| ID | Date | Subject | Minutes | Pomodoros | Break | Notes |",
          "|---:|---|---|---:|---:|---:|---|"]
    for s in sorted(sessions, key=lambda x: (x.date, x.id)):
        L.append(f"| {s.id} | {s.date} | {s.subject} | {s.focused_minutes} | {s.pomodoros} "
                 f"| {s.break_minutes} | {s.notes.replace('|', '/')} |")
    return "\n".join(L) + "\n"


def render_audit_text(sessions: list[Session], summary: dict, warns: list[Warn]) -> str:
    ordered = sorted(sessions, key=lambda x: (x.date, x.id))
    body = "\n".join(f"{s.id}|{s.date}|{s.subject}|{s.focused_minutes}|{s.pomodoros}|"
                     f"{s.break_minutes}|{s.notes}" for s in ordered)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    L = ["=" * 78, f"{APP_NAME.upper()} - AUDIT LOG", "=" * 78,
         f"Generated      : {datetime.now():%Y-%m-%d %H:%M:%S}",
         f"Data as of     : {summary['as_of']}",
         f"Records        : {len(ordered)}",
         f"Total minutes  : {summary['total_minutes']}",
         f"SHA-256 (data) : {digest}", "",
         "-- SUBJECT TOTALS " + "-" * 59]
    for r in summary["by_subject"]:
        L.append(f"  {r['subject']:<28}{r['minutes']:>6} min {r['sessions']:>4} sessions {r['share']:>6}%")
    L += ["", f"-- STATUS: {summary['status']} - {summary['status_detail']}",
          f"-- TREND : {summary['trend']}", "", "-- WARNINGS " + "-" * 64]
    L += [f"  [{w.level:<8}] {w.code}: {w.message}" for w in warns] or ["  none"]
    L += ["", "-- RECORDS " + "-" * 66,
          f"  {'ID':>4} {'DATE':<10} {'SUBJECT':<26}{'MIN':>5}{'POM':>5}{'BRK':>5}  NOTES"]
    for s in ordered:
        L.append(f"  {s.id:>4} {s.date:<10} {s.subject[:25]:<26}{s.focused_minutes:>5}"
                 f"{s.pomodoros:>5}{s.break_minutes:>5}  {s.notes}")
    L += ["", "=" * 78, "END OF LOG", ""]
    return "\n".join(L)


def render_sessions_csv(sessions: Iterable[Session]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(SESSION_FIELDS)
    for s in sorted(sessions, key=lambda x: (x.date, x.id)):
        w.writerow([getattr(s, f) for f in SESSION_FIELDS])
    return buf.getvalue()


def render_subject_csv(sessions: Iterable[Session]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["subject", "focused_minutes", "sessions", "pomodoros", "avg_session_min", "share_percent"])
    for r in minutes_by_subject(sessions):
        w.writerow([r["subject"], r["minutes"], r["sessions"], r["pomodoros"],
                    r["avg_session"], r["share"]])
    return buf.getvalue()


# --------------------------------------------------------------------- charts
def save_chart(sessions: list[Session], path: str | Path) -> Path | None:
    """PNG with minutes-by-subject and the daily trend. None if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    if not sessions:
        return None
    rows = minutes_by_subject(sessions)
    days = daily_totals(sessions)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8))
    a1.barh([r["subject"] for r in rows][::-1], [r["minutes"] for r in rows][::-1], color="#e5484d")
    a1.set_title("Focused minutes by subject")
    a1.set_xlabel("minutes")
    xs = [datetime.strptime(d, "%Y-%m-%d") for d in days]
    a2.plot(xs, list(days.values()), marker="o", color="#2f9e6e")
    a2.set_title("Daily focused minutes")
    a2.set_ylabel("minutes")
    fig.autofmt_xdate()
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def text_bar_chart(rows: list[dict], width: int = 36) -> list[str]:
    """Zero-dependency fallback chart used by the terminal UI."""
    if not rows:
        return []
    peak = max(r["minutes"] for r in rows) or 1
    lines = []
    for r in rows:
        bar = "█" * max(1, round(width * r["minutes"] / peak))
        lines.append(f"{r['subject'][:18]:<18} {bar} {r['minutes']}")
    return lines


# ------------------------------------------------------------------ write all
def export_all(sessions: list[Session], out_dir: str | Path = "exports",
               today: date | None = None, settings: dict | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = settings or {}
    summary = build_summary(sessions, today, cfg.get("daily_goal", 120))
    warns = get_warnings(sessions, today, cfg)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files = {
        f"report_{stamp}.md": render_markdown(sessions, summary, warns),
        f"audit_log_{stamp}.txt": render_audit_text(sessions, summary, warns),
        f"sessions_{stamp}.csv": render_sessions_csv(sessions),
        f"subject_summary_{stamp}.csv": render_subject_csv(sessions),
    }
    paths = []
    for name, content in files.items():
        p = out_dir / name
        p.write_text(content, encoding="utf-8", newline="")
        paths.append(p)
    chart = save_chart(sessions, out_dir / f"chart_{stamp}.png")
    if chart:
        paths.append(chart)
    return paths
