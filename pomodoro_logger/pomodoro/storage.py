"""JSON persistence with corruption recovery and atomic writes."""
from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import DEFAULT_SETTINGS, SCHEMA_VERSION, SESSION_FIELDS, Session
from .validation import ValidationError, validate_session_fields


class Storage:
    """Owns the data file. Loads on construction; mutate via add/delete."""

    def __init__(self, path: str | os.PathLike = "data/sessions.json"):
        self.path = Path(path)
        self.sessions: list[Session] = []
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.next_id: int = 1
        self.load_notes: list[str] = []   # human-readable recovery messages
        self.load()

    # ------------------------------------------------------------- loading
    def load(self) -> None:
        self.load_notes = []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list):
                raise ValueError("unexpected file structure")
        except FileNotFoundError:
            self.load_notes.append(f"No data file found - created a fresh one at {self.path}.")
            self._reset()
            return
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
            backup = self._backup_corrupt()
            self.load_notes.append(
                f"Data file was unreadable ({exc.__class__.__name__}). "
                f"Backed it up to {backup.name if backup else '(backup failed)'} and started fresh."
            )
            self._reset()
            return

        saved = raw.get("settings")
        saved = saved if isinstance(saved, dict) else {}
        self.settings = {**DEFAULT_SETTINGS,
                         **{k: v for k, v in saved.items()
                            if k in DEFAULT_SETTINGS and isinstance(v, int) and v > 0}}
        self.sessions = []
        dropped = 0
        seen_ids: set[int] = set()
        for rec in raw["sessions"]:
            try:
                if not isinstance(rec, dict):
                    raise ValidationError("record is not an object")
                # Records were validated on entry; tolerate clock/timezone drift on reload.
                clean = validate_session_fields(rec, date.today() + timedelta(days=2))
                sid = rec.get("id")
                if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1 or sid in seen_ids:
                    raise ValidationError("bad or duplicate id")
                seen_ids.add(sid)
                self.sessions.append(Session(
                    id=sid, created_at=str(rec.get("created_at") or ""), **clean))
            except ValidationError:
                dropped += 1
        if dropped:
            self.load_notes.append(f"Skipped {dropped} invalid record(s) while loading.")
        next_id = raw.get("next_id")
        floor = max((s.id for s in self.sessions), default=0) + 1
        self.next_id = max(next_id if isinstance(next_id, int) else 1, floor)
        if dropped:
            self.save()

    def _reset(self) -> None:
        self.sessions, self.settings, self.next_id = [], dict(DEFAULT_SETTINGS), 1
        self.save()

    def _backup_corrupt(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.path.with_suffix(f".corrupt-{stamp}.bak")
        try:
            shutil.copy2(self.path, dest)
            return dest
        except OSError:
            return None

    # -------------------------------------------------------------- saving
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "next_id": self.next_id,
            "settings": self.settings,
            "sessions": [s.to_dict() for s in self.sessions],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)       # atomic: never leaves a half-written file

    # ------------------------------------------------------------ mutation
    def add(self, fields: dict, save: bool = True) -> Session:
        """Add an already-validated record."""
        sess = Session(
            id=self.next_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            **{k: fields[k] for k in SESSION_FIELDS if k not in ("id", "created_at")})
        self.sessions.append(sess)
        self.next_id += 1
        if save:
            self.save()
        return sess

    def delete(self, session_id: int) -> bool:
        before = len(self.sessions)
        self.sessions = [s for s in self.sessions if s.id != session_id]
        changed = len(self.sessions) != before
        if changed:
            self.save()
        return changed

    def update_settings(self, **kwargs: int) -> None:
        for key, val in kwargs.items():
            if key in DEFAULT_SETTINGS:
                self.settings[key] = int(val)
        self.save()
