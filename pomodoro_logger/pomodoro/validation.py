"""Centralised, defensive input validation.

Every validator takes a raw value (usually a string), returns a cleaned value
and raises ``ValidationError`` with a friendly message otherwise. The CLI
wraps them in ``ask()`` (loops until valid) and the GUI shows the messages
inline, so both front-ends share exactly the same rules.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Callable

from .models import (
    MIN_FOCUS, MAX_FOCUS, MIN_POMO, MAX_POMO, MAX_BREAK, MAX_MIN_PER_POMO,
    SUBJECT_MIN_LEN, SUBJECT_MAX_LEN, NOTES_MAX_LEN, STANDARD_POMODORO,
)


class ValidationError(ValueError):
    """Raised when a value does not meet the domain constraints."""


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SUBJECT_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,&+#'/()\-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")


def _clean(raw: Any) -> str:
    if raw is None:
        return ""
    return _CONTROL_CHARS.sub(" ", str(raw)).strip()


def parse_int(raw: Any, label: str, lo: int, hi: int) -> int:
    text = _clean(raw)
    if not text:
        raise ValidationError(f"{label} cannot be blank.")
    # accept "45", "45.0" but reject "45.5", "abc", "1e3", "NaN"
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        text = text.split(".")[0]
    if not _INT_RE.match(text):
        raise ValidationError(f"{label} must be a whole number (got '{text}').")
    value = int(text)
    if not lo <= value <= hi:
        raise ValidationError(f"{label} must be between {lo} and {hi} (got {value}).")
    return value


def validate_date(raw: Any, today: date | None = None) -> str:
    today = today or date.today()
    text = _clean(raw)
    if not text:
        raise ValidationError("Date cannot be blank.")
    if not _DATE_RE.match(text):
        raise ValidationError("Date must use the format YYYY-MM-DD (e.g. 2026-11-25).")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"'{text}' is not a real calendar date.") from None
    if parsed > today:
        raise ValidationError("Date cannot be in the future.")
    if parsed.year < 2000:
        raise ValidationError("Date must be in the year 2000 or later.")
    return parsed.isoformat()


def validate_subject(raw: Any) -> str:
    text = re.sub(r"\s+", " ", _clean(raw))
    if not text:
        raise ValidationError("Subject cannot be blank.")
    if len(text) < SUBJECT_MIN_LEN:
        raise ValidationError(f"Subject must be at least {SUBJECT_MIN_LEN} characters.")
    if len(text) > SUBJECT_MAX_LEN:
        raise ValidationError(f"Subject must be at most {SUBJECT_MAX_LEN} characters.")
    if not _SUBJECT_OK.match(text):
        raise ValidationError(
            "Subject may contain letters, digits, spaces and . , & + # ' / ( ) - only."
        )
    # Normalise so "math", "MATH" and "Math" aggregate together
    # (short all-caps words such as "AI" or "DSA" are kept as typed).
    return " ".join(w if (w.isupper() and 1 < len(w) <= 4) else w.capitalize()
                    for w in text.split(" "))


def validate_minutes(raw: Any) -> int:
    return parse_int(raw, "Focused minutes", MIN_FOCUS, MAX_FOCUS)


def validate_pomodoros(raw: Any) -> int:
    return parse_int(raw, "Pomodoros", MIN_POMO, MAX_POMO)


def validate_break(raw: Any) -> int:
    text = _clean(raw)
    if not text:
        return 0
    return parse_int(text, "Break minutes", 0, MAX_BREAK)


def validate_notes(raw: Any) -> str:
    text = re.sub(r"\s+", " ", _clean(raw))
    if len(text) > NOTES_MAX_LEN:
        raise ValidationError(f"Notes must be at most {NOTES_MAX_LEN} characters (got {len(text)}).")
    return text


def default_pomodoros(minutes: int) -> int:
    """Suggested pomodoro count for a number of focused minutes."""
    return max(MIN_POMO, min(MAX_POMO, math.ceil(minutes / STANDARD_POMODORO)))


def check_consistency(minutes: int, pomodoros: int) -> None:
    """Cross-field rule: minutes and pomodoros must plausibly match."""
    if minutes > pomodoros * MAX_MIN_PER_POMO:
        raise ValidationError(
            f"{minutes} focused minutes is too many for {pomodoros} pomodoro(s) "
            f"(max {MAX_MIN_PER_POMO} min each). Increase the pomodoro count."
        )
    if minutes < pomodoros:
        raise ValidationError(
            f"{pomodoros} pomodoro(s) cannot fit into only {minutes} focused minute(s)."
        )


def validate_session_fields(data: dict, today: date | None = None) -> dict:
    """Validate a whole record. Collects *all* errors, raising once.

    ``pomodoros`` may be blank -> derived from minutes (25-min blocks).
    Returns the cleaned dict (without id / created_at).
    """
    errors: list[str] = []
    out: dict[str, Any] = {}

    def run(key: str, fn: Callable[[Any], Any]) -> None:
        try:
            out[key] = fn(data.get(key))
        except ValidationError as exc:
            errors.append(str(exc))

    run("date", lambda v: validate_date(v, today))
    run("subject", validate_subject)
    run("focused_minutes", validate_minutes)
    run("break_minutes", validate_break)
    run("notes", validate_notes)

    if _clean(data.get("pomodoros")) == "":
        # blank = auto (derived from minutes); if minutes are invalid that error is
        # already reported, so don't add a misleading "pomodoros blank" message.
        if "focused_minutes" in out:
            out["pomodoros"] = default_pomodoros(out["focused_minutes"])
    else:
        run("pomodoros", validate_pomodoros)

    if not errors:
        try:
            check_consistency(out["focused_minutes"], out["pomodoros"])
        except ValidationError as exc:
            errors.append(str(exc))
    if errors:
        raise ValidationError(" | ".join(errors))
    return out


# ---------------------------------------------------------------- CLI helper
def ask(prompt: str, validator: Callable[[Any], Any], default: Any = None,
        allow_cancel: bool = True, input_fn: Callable[[str], str] = input,
        print_fn: Callable[..., None] = print) -> Any:
    """Prompt until ``validator`` accepts the answer.

    * Enter on a prompt with a ``default`` uses the default.
    * Typing ``q`` (when allow_cancel) returns ``None`` so callers can abort.
    * Ctrl-D / Ctrl-C are treated as cancel instead of crashing.
    """
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            raw = input_fn(f"  {prompt}{suffix}: ")
        except (EOFError, KeyboardInterrupt):
            print_fn()
            return None
        if allow_cancel and raw.strip().lower() in {"q", "quit", "cancel"}:
            return None
        if raw.strip() == "" and default not in (None, ""):
            raw = str(default)
        try:
            return validator(raw)
        except ValidationError as exc:
            print_fn(f"  ✗ {exc}  (try again, or 'q' to cancel)")
