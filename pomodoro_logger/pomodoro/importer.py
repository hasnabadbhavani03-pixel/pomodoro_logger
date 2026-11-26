"""Bulk CSV import with automatic validation and a row-by-row error log."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .storage import Storage
from .validation import ValidationError, validate_session_fields

REQUIRED = ("date", "subject", "focused_minutes")
OPTIONAL = ("pomodoros", "break_minutes", "notes")
ALIASES = {
    "minutes": "focused_minutes", "focus_minutes": "focused_minutes",
    "focused": "focused_minutes", "duration": "focused_minutes",
    "topic": "subject", "course": "subject", "pomos": "pomodoros",
    "break": "break_minutes", "breaks": "break_minutes", "note": "notes",
    "comment": "notes", "comments": "notes",
}
MAX_ROWS = 20000


@dataclass
class ImportResult:
    total_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)   # (line number, reason)
    fatal: str = ""
    log_path: Path | None = None

    @property
    def rejected(self) -> int:
        return len(self.errors)

    def summary_line(self) -> str:
        if self.fatal:
            return f"Import failed: {self.fatal}"
        return (f"{self.total_rows} data row(s): {self.imported} imported, "
                f"{self.duplicates} duplicate(s) skipped, {self.rejected} rejected.")


def _norm(name: str) -> str:
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(key, key)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def write_error_log(result: ImportResult, source: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"Import log - {datetime.now():%Y-%m-%d %H:%M:%S}", f"Source: {source}",
             result.summary_line(), ""]
    if result.fatal:
        lines.append(f"FATAL: {result.fatal}")
    for row, reason in result.errors:
        lines.append(f"Row {row}: {reason}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def import_csv_text(text: str, storage: Storage, today: date | None = None) -> ImportResult:
    res = ImportResult()
    text = text.lstrip("\ufeff")                 # strip a UTF-8 byte-order mark if present
    try:
        first_line = text.lstrip("\ufeff").split("\n", 1)[0]
        delim = max(",;\t", key=lambda c: first_line.count(c))   # comma wins ties
        if first_line.count(delim) == 0:
            delim = ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        header = next(reader, None)
        if not header or not any(h.strip() for h in header):
            res.fatal = "file is empty or has no header row."
            return res
        cols = [_norm(h) for h in header]
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            res.fatal = (f"missing required column(s): {', '.join(missing)}. "
                         f"Found: {', '.join(h.strip() or '(blank)' for h in header)}.")
            return res
        if len(set(cols)) != len(cols):
            res.fatal = "duplicate column names in header."
            return res

        existing = {(s.date, s.subject, s.focused_minutes, s.notes) for s in storage.sessions}
        for row in reader:
            line = reader.line_num
            if not row or not any(c.strip() for c in row):
                continue                                   # silently skip blank lines
            res.total_rows += 1
            if res.total_rows > MAX_ROWS:
                res.errors.append((line, f"stopped: more than {MAX_ROWS} rows."))
                break
            if len(row) != len(cols):
                res.errors.append((line, f"expected {len(cols)} columns but found {len(row)}."))
                continue
            record = dict(zip(cols, row))
            try:
                clean = validate_session_fields(record, today)
            except ValidationError as exc:
                res.errors.append((line, str(exc)))
                continue
            key = (clean["date"], clean["subject"], clean["focused_minutes"], clean["notes"])
            if key in existing:
                res.duplicates += 1
                continue
            existing.add(key)
            storage.add(clean, save=False)
            res.imported += 1
        if res.imported:
            storage.save()
    except csv.Error as exc:
        res.fatal = f"CSV parsing error: {exc}"
    return res


def import_csv_file(path: str | Path, storage: Storage, log_path: str | Path = "exports/import_errors.log",
                    today: date | None = None) -> ImportResult:
    path = Path(path)
    try:
        text = _decode(path.read_bytes())
    except FileNotFoundError:
        res = ImportResult(fatal=f"file not found: {path}")
    except (IsADirectoryError, PermissionError, OSError) as exc:
        res = ImportResult(fatal=f"cannot read file ({exc.__class__.__name__}).")
    else:
        res = import_csv_text(text, storage, today)
    if res.errors or res.fatal:
        res.log_path = write_error_log(res, str(path), Path(log_path))
    return res
