"""Data structures and domain constants."""
from __future__ import annotations

from dataclasses import dataclass, asdict

# ---- Domain limits (used by validation, warnings and the GUI) -------------
MIN_FOCUS, MAX_FOCUS = 1, 480          # focused minutes per session
MIN_POMO, MAX_POMO = 1, 20             # pomodoros per session
MAX_BREAK = 240                        # break minutes per session
MAX_MIN_PER_POMO = 90                  # a "pomodoro" may be stretched, but not beyond this
SUBJECT_MIN_LEN, SUBJECT_MAX_LEN = 2, 40
NOTES_MAX_LEN = 200
STANDARD_POMODORO = 25                 # classic 25-minute block

# ---- Default, user-changeable settings ------------------------------------
DEFAULT_SETTINGS = {
    "daily_goal": 120,        # minutes/day considered "on target"
    "daily_limit": 480,       # minutes/day that triggers an overload warning
    "anomaly_session": 400,   # single session length that is flagged as unusual
    "inactive_days": 3,       # days without study before a warning
}

SCHEMA_VERSION = 1


@dataclass
class Session:
    id: int
    date: str                 # YYYY-MM-DD
    subject: str
    focused_minutes: int
    pomodoros: int
    break_minutes: int
    notes: str
    created_at: str           # ISO timestamp

    def to_dict(self) -> dict:
        return asdict(self)


SESSION_FIELDS = [
    "id", "date", "subject", "focused_minutes",
    "pomodoros", "break_minutes", "notes", "created_at",
]
