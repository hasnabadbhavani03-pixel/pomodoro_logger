#!/usr/bin/env python3
"""Generate realistic sample data (40 sessions) + a deliberately dirty CSV.

Outputs (in ./data):
  sample_sessions.csv   - 40 valid sessions, importable via the app
  sample_sessions.json  - same data in the app's native storage format
  dirty_import.csv      - mixed good/bad rows to demo import validation
  sessions.json         - (with --load) the live data file, seeded with the sample

Usage:  python generate_sample_data.py [--end YYYY-MM-DD] [--load]
        (data ends yesterday by default, so it is valid on any machine's clock)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from pomodoro.models import DEFAULT_SETTINGS, SCHEMA_VERSION
from pomodoro.validation import validate_session_fields

SUBJECTS = {
    "Mathematics": ["Calculus practice set", "Linear algebra revision", "Probability problems", "Integration by parts drills"],
    "Physics": ["Kinematics numericals", "Optics lab report", "Thermodynamics notes", "Electromagnetism revision"],
    "Chemistry": ["Organic reactions summary", "Periodic trends flashcards", "Titration lab prep"],
    "Python Programming": ["Built a CLI todo app", "File handling exercises", "Decorators and generators", "Hackathon prep"],
    "Data Structures": ["Linked list problems", "Binary trees", "Graph traversal BFS/DFS", "Sorting algorithms"],
    "English Literature": ["Essay draft on Hamlet", "Poetry analysis", "Reading assignment"],
    "History": ["Industrial revolution notes", "Timeline memorisation"],
    "Machine Learning": ["Linear regression from scratch", "Watched lecture series", "Kaggle notebook"],
}
GAP_OFFSETS = {5, 6, 12, 13, 19, 24}          # days with no study (for streak / gap demos)
MINUTE_CHOICES = [25, 30, 45, 50, 60, 75, 90, 100, 120]


def build(end: date) -> list[dict]:
    rng = random.Random(103)                   # project number -> reproducible data
    rows: list[dict] = []
    base = [o for o in range(27, -1, -1) if o not in GAP_OFFSETS]
    offsets = sorted(base + rng.sample(base, 34 - len(base)), reverse=True)   # some days get 2 sessions
    subjects = list(SUBJECTS)
    for i, off in enumerate(offsets):
        subj = subjects[(i * 3 + rng.randint(0, 2)) % len(subjects)]
        mins = rng.choice(MINUTE_CHOICES)
        pomo = max(1, math.ceil(mins / 25))
        rows.append(dict(date=(end - timedelta(days=off)).isoformat(), subject=subj,
                         focused_minutes=mins, pomodoros=pomo,
                         break_minutes=pomo * 5 - 5 if pomo > 1 else 0,
                         notes=rng.choice(SUBJECTS[subj])))
    d = lambda off: (end - timedelta(days=off)).isoformat()
    rows += [  # --- boundary values & edge conditions --------------------------------
        dict(date=d(20), subject="Mathematics", focused_minutes=1, pomodoros=1, break_minutes=0,
             notes="Quick formula check (minimum boundary)"),
        dict(date=d(15), subject="Physics", focused_minutes=480, pomodoros=8, break_minutes=60,
             notes="Exam-eve marathon (maximum boundary)"),
        dict(date=d(15), subject="Chemistry", focused_minutes=90, pomodoros=4, break_minutes=15,
             notes="Late-night extra revision -> day exceeds limit"),
        dict(date=d(9), subject="Data Structures", focused_minutes=40, pomodoros=6, break_minutes=10,
             notes="Distracted: 6 pomodoros but only 40 min (ratio anomaly)"),
        dict(date=d(3), subject="Python Programming", focused_minutes=10, pomodoros=1, break_minutes=20,
             notes='Revised "decorators", generators, & closures - comma/quote test'),
        dict(date=d(3), subject="Python Programming", focused_minutes=10, pomodoros=1, break_minutes=20,
             notes='Revised "decorators", generators, & closures - comma/quote test'),  # duplicate
    ]
    rows = rows[:40]
    rows.sort(key=lambda r: r["date"])
    for r in rows:                              # fail loudly if sample data is invalid
        validate_session_fields(r, end)
    return rows


DIRTY = """Date,Topic,Minutes,Pomodoros,Break,Notes
{d0},Mathematics,50,2,5,Valid row using alias column names
{d1},physics,75,3,10,Valid row - subject normalised to Physics
25/11/2026,Chemistry,30,1,5,Bad date format
{future},History,45,2,5,Date in the future
{d2},,45,2,5,Blank subject
{d2},Mathematics,abc,2,5,Non-numeric minutes
{d2},Mathematics,0,1,0,Minutes below minimum
{d2},Mathematics,600,10,0,Minutes above maximum
{d2},Mathematics,45.5,2,5,Fractional minutes
{d2},Mathematics,200,1,0,Minutes impossible for one pomodoro
{d2},Mathematics,45,2,5,Too many columns,extra
{d2},Mathematics,45
{d2},<script>alert(1)</script>,30,1,5,Unsafe characters in subject
{d3},Data Structures,60,3,10,Valid row
{d3},Data Structures,60,3,10,Valid row
{d4},English Literature,25,,0,Valid - pomodoros left blank (auto 1)
2026-02-30,Mathematics,30,1,5,Impossible calendar date

{d4},Machine Learning,90,4,15,Valid row
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", help="last date of the data (default: yesterday, so it is never a 'future' date)")
    ap.add_argument("--load", action="store_true", help="also overwrite data/sessions.json with the sample")
    args = ap.parse_args()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today() - timedelta(days=1)
    out = Path("data")
    out.mkdir(exist_ok=True)
    rows = build(end)

    fields = ["date", "subject", "focused_minutes", "pomodoros", "break_minutes", "notes"]
    with open(out / "sample_sessions.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    stamp = datetime.now().isoformat(timespec="seconds")
    payload = {"schema_version": SCHEMA_VERSION, "next_id": len(rows) + 1,
               "settings": dict(DEFAULT_SETTINGS),
               "sessions": [{"id": i, "created_at": stamp,
                             **validate_session_fields(r, end)} for i, r in enumerate(rows, 1)]}
    (out / "sample_sessions.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.load:
        (out / "sessions.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    dd = lambda off: (end - timedelta(days=off)).isoformat()
    (out / "dirty_import.csv").write_text(DIRTY.format(
        d0=dd(2), d1=dd(1), d2=dd(7), d3=dd(8), d4=dd(10),
        future=(end + timedelta(days=30)).isoformat()), encoding="utf-8")
    print(f"Wrote {len(rows)} sessions ({rows[0]['date']} -> {rows[-1]['date']}) to {out}/"
          + (" and loaded data/sessions.json" if args.load else ""))


if __name__ == "__main__":
    main()
