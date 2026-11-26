"""Interactive, menu-driven terminal interface (ANSI colours, paginated tables)."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence

from . import APP_NAME, __version__
from .export import export_all, text_bar_chart
from .importer import import_csv_file
from .logic import (daily_totals, fmt_minutes, minutes_by_subject, record_session, search,
                    subjects as list_subjects)
from .models import MAX_BREAK, MAX_FOCUS, NOTES_MAX_LEN
from .storage import Storage
from .summary import build_summary
from .validation import (ValidationError, ask, check_consistency, default_pomodoros,
                         parse_int, validate_break, validate_date, validate_minutes,
                         validate_notes, validate_pomodoros, validate_subject)
from .warnings_ import get_warnings

PAGE_SIZE = 10


# ------------------------------------------------------------------- styling
def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")          # enables ANSI escape processing on Windows 10+
    return True


class Style:
    def __init__(self, enabled: bool):
        self.on = enabled

    def _w(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.on else text

    def red(self, t): return self._w("31", t)
    def green(self, t): return self._w("32", t)
    def yellow(self, t): return self._w("33", t)
    def cyan(self, t): return self._w("36", t)
    def bold(self, t): return self._w("1", t)
    def dim(self, t): return self._w("2", t)
    def tomato(self, t): return self._w("1;38;5;196", t)


BANNER = r"""
        __/\__
       /  \/  \        ____                      _
      | (    ) |      |  _ \ ___  _ __ ___   ___ | |_ ___  _ __ ___
      |  \__/  |      | |_) / _ \| '_ ` _ \ / _ \| __/ _ \| '__/ _ \
       \      /       |  __/ (_) | | | | | | (_) | || (_) | | | (_) |
        `----'        |_|   \___/|_| |_| |_|\___/ \__\___/|_|  \___/
"""


class CLI:
    def __init__(self, storage: Storage, export_dir: str = "exports",
                 input_fn: Callable[[str], str] = input,
                 print_fn: Callable[..., None] = print,
                 color: bool | None = None, today: date | None = None):
        self.storage = storage
        self.export_dir = export_dir
        self.inp = input_fn
        self.out = print_fn
        self.st = Style(_color_enabled() if color is None else color)
        self.today = today or date.today()

    # -------------------------------------------------------------- helpers
    def say(self, text: str = "") -> None:
        self.out(text)

    def ask(self, prompt: str, validator: Callable[[Any], Any], default: Any = None) -> Any:
        return ask(prompt, validator, default, input_fn=self.inp,
                   print_fn=lambda *a: self.out(*[self.st.red(str(x)) if "✗" in str(x) else x for x in a]))

    @staticmethod
    def optional(validator: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Wrap a validator so a blank answer means 'skip' (returns '')."""
        return lambda raw: "" if str(raw).strip() == "" else validator(raw)

    def pause(self) -> None:
        try:
            self.inp(self.st.dim("\n  Press Enter to continue..."))
        except (EOFError, KeyboardInterrupt):
            pass

    def heading(self, title: str) -> None:
        self.say("\n" + self.st.bold(self.st.cyan(f"── {title} " + "─" * max(4, 60 - len(title)))))

    def confirm(self, prompt: str, default_yes: bool = False) -> bool:
        hint = "Y/n" if default_yes else "y/N"
        try:
            raw = self.inp(f"  {prompt} [{hint}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return default_yes if raw == "" else raw in {"y", "yes"}

    # ----------------------------------------------------------------- table
    @staticmethod
    def _cell(value: Any, width: int, align: str) -> str:
        text = str(value)
        if len(text) > width:
            text = text[: width - 1] + "…"
        return text.rjust(width) if align == ">" else text.ljust(width)

    def table(self, rows: Sequence[dict], columns: Sequence[tuple[str, str, int, str]]) -> None:
        """columns = (header, key, width, align '<' or '>')."""
        head = " │ ".join(self._cell(h, w, a) for h, _, w, a in columns)
        rule = "─┼─".join("─" * w for _, _, w, _ in columns)
        self.say("  " + self.st.bold(head))
        self.say("  " + rule)
        for r in rows:
            self.say("  " + " │ ".join(self._cell(r[k], w, a) for _, k, w, a in columns))

    SESSION_COLS = [("ID", "id", 4, ">"), ("Date", "date", 10, "<"), ("Subject", "subject", 20, "<"),
                    ("Min", "focused_minutes", 4, ">"), ("Pom", "pomodoros", 3, ">"),
                    ("Brk", "break_minutes", 3, ">"), ("Notes", "notes", 30, "<")]

    def paginate(self, sessions: list) -> None:
        if not sessions:
            self.say(self.st.yellow("  No matching sessions."))
            return
        pages = (len(sessions) - 1) // PAGE_SIZE + 1
        page = 0
        while True:
            chunk = sessions[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            self.table([s.to_dict() for s in chunk], self.SESSION_COLS)
            total = sum(s.focused_minutes for s in sessions)
            self.say(self.st.dim(f"\n  Page {page + 1}/{pages} · {len(sessions)} record(s) · {total} min total"))
            if pages == 1:
                return
            try:
                cmd = self.inp("  [n]ext  [p]rev  [q]uit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return
            if cmd in {"n", ""} and page < pages - 1:
                page += 1
            elif cmd == "p" and page > 0:
                page -= 1
            elif cmd in {"q", "quit"}:
                return

    # ------------------------------------------------------------- welcome
    def welcome(self) -> None:
        self.say(self.st.tomato(BANNER))
        self.say(self.st.bold(f"  {APP_NAME}  v{__version__}"))
        self.say(self.st.dim("  Track focused minutes by subject · Stay on target · Build a streak"))
        for note in self.storage.load_notes:
            self.say(self.st.yellow(f"  ⚠ {note}"))
        n = len(self.storage.sessions)
        self.say(self.st.dim(f"  Data file: {self.storage.path} ({n} session{'s' if n != 1 else ''} loaded)"))

    MENU = [("1", "Log a new study session"), ("2", "View all sessions"),
            ("3", "Search & filter"), ("4", "Summary dashboard"),
            ("5", "Warnings & alerts"), ("6", "Export reports (MD / TXT / CSV / chart)"),
            ("7", "Bulk import from CSV"), ("8", "Delete a session"),
            ("9", "Settings"), ("0", "Exit")]

    def run(self) -> int:
        self.welcome()
        handlers = {"1": self.log_session, "2": self.view_all, "3": self.search_menu,
                    "4": self.dashboard, "5": self.show_warnings, "6": self.export,
                    "7": self.bulk_import, "8": self.delete_session, "9": self.settings}
        while True:
            self.heading("MAIN MENU")
            for key, label in self.MENU:
                self.say(f"   {self.st.bold(key)}  {label}")
            try:
                choice = self.inp("\n  Choose an option: ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "0"
            if choice == "0":
                self.say(self.st.green("\n  Data saved. Keep focusing! 🍅\n"))
                return 0
            if choice == "":
                continue
            handler = handlers.get(choice)
            if handler is None:
                self.say(self.st.red(f"  ✗ '{choice}' is not a valid option - enter a number from the menu."))
                continue
            try:
                handler()
            except KeyboardInterrupt:
                self.say(self.st.yellow("\n  Cancelled."))
            except OSError as exc:
                self.say(self.st.red(f"  ✗ File error: {exc}"))

    # ------------------------------------------------------------ 1. log
    def log_session(self) -> None:
        self.heading("LOG A NEW SESSION  (type q to cancel)")
        known = list_subjects(self.storage.sessions)
        if known:
            self.say(self.st.dim("  Known subjects: " + ", ".join(known)))
        d = self.ask("Date YYYY-MM-DD", lambda v: validate_date(v, self.today), self.today.isoformat())
        if d is None: return self.cancelled()
        subj = self.ask("Subject", validate_subject)
        if subj is None: return self.cancelled()
        mins = self.ask(f"Focused minutes (1-{MAX_FOCUS})", validate_minutes)
        if mins is None: return self.cancelled()

        def pomo_validator(raw: str) -> int:
            n = validate_pomodoros(raw)
            check_consistency(mins, n)
            return n
        pomo = self.ask("Pomodoros completed", pomo_validator, default_pomodoros(mins))
        if pomo is None: return self.cancelled()
        brk = self.ask(f"Break minutes (0-{MAX_BREAK}, optional)", validate_break, 0)
        if brk is None: return self.cancelled()
        notes = self.ask(f"Notes (optional, max {NOTES_MAX_LEN})", validate_notes, "")
        if notes is None: return self.cancelled()

        self.say(f"\n  {self.st.bold('Review:')} {d} · {subj} · {mins} min · {pomo} pomodoro(s) "
                 f"· break {brk} min" + (f" · “{notes}”" if notes else ""))
        if not self.confirm("Save this session?", default_yes=True):
            return self.cancelled()
        try:
            s = record_session(self.storage, dict(date=d, subject=subj, focused_minutes=mins,
                                                  pomodoros=pomo, break_minutes=brk, notes=notes),
                               self.today)
        except ValidationError as exc:        # defensive: should be unreachable
            self.say(self.st.red(f"  ✗ {exc}"))
            return
        self.say(self.st.green(f"  ✓ Saved as session #{s.id}."))
        day_total = daily_totals(self.storage.sessions)[s.date]
        limit = self.storage.settings["daily_limit"]
        if day_total > limit:
            self.say(self.st.red(f"  ⚠ {s.date} now totals {day_total} min - above your {limit} min daily limit!"))
        else:
            self.say(self.st.dim(f"  {s.date} total so far: {fmt_minutes(day_total)}"))

    def cancelled(self) -> None:
        self.say(self.st.yellow("  Cancelled - nothing was saved."))

    # ------------------------------------------------------- 2. view all
    def view_all(self) -> None:
        self.heading("ALL SESSIONS (newest first)")
        self.paginate(search(self.storage.sessions))

    # ------------------------------------------------------ 3. search
    def search_menu(self) -> None:
        self.heading("SEARCH & FILTER  (blank = skip a filter, q = cancel)")
        kw = self.ask("Keyword (subject or notes)", self.optional(lambda v: " ".join(str(v).split())))
        if kw is None: return self.cancelled()
        known = list_subjects(self.storage.sessions)
        if known:
            self.say(self.st.dim("  Subjects: " + ", ".join(known)))
        subj = self.ask("Category / subject contains", self.optional(lambda v: " ".join(str(v).split())))
        if subj is None: return self.cancelled()
        dv = self.optional(lambda v: validate_date(v, date(2100, 1, 1)))
        dfrom = self.ask("From date YYYY-MM-DD", dv)
        if dfrom is None: return self.cancelled()
        dto = self.ask("To date YYYY-MM-DD", dv)
        if dto is None: return self.cancelled()
        if dfrom and dto and dfrom > dto:
            self.say(self.st.yellow("  From-date is after To-date - swapping them."))
            dfrom, dto = dto, dfrom
        mn = self.ask("Min minutes", self.optional(lambda v: parse_int(v, "Min minutes", 0, MAX_FOCUS)))
        if mn is None: return self.cancelled()
        mx = self.ask("Max minutes", self.optional(lambda v: parse_int(v, "Max minutes", 0, MAX_FOCUS)))
        if mx is None: return self.cancelled()
        if mn != "" and mx != "" and mn > mx:
            self.say(self.st.yellow("  Min is greater than Max - swapping them."))
            mn, mx = mx, mn

        def sort_validator(v: str) -> str:
            v = str(v).strip().lower()
            if v not in {"date", "subject", "minutes", "pomodoros"}:
                raise ValidationError("Choose date, subject, minutes or pomodoros.")
            return v
        sort_by = self.ask("Sort by (date/subject/minutes/pomodoros)", sort_validator, "date")
        if sort_by is None: return self.cancelled()
        results = search(self.storage.sessions, kw, subj, dfrom or None, dto or None,
                         None if mn == "" else mn, None if mx == "" else mx, sort_by,
                         descending=sort_by in {"date", "minutes", "pomodoros"})
        self.heading(f"{len(results)} RESULT(S)")
        self.paginate(results)
        if results:
            self.say("\n  " + self.st.bold("By subject:"))
            for line in text_bar_chart(minutes_by_subject(results)):
                self.say("  " + line)

    # ------------------------------------------------------ 4. dashboard
    STATUS_COLOR = {"ON TRACK": "green", "NEEDS FOCUS": "yellow", "BEHIND": "red",
                    "INACTIVE": "red", "NO DATA": "dim"}

    def dashboard(self) -> None:
        sm = build_summary(self.storage.sessions, self.today, self.storage.settings["daily_goal"])
        self.heading("EXECUTIVE SUMMARY")
        if not sm["total_sessions"]:
            self.say(self.st.yellow("  " + sm["status_detail"]))
            return
        colour = getattr(self.st, self.STATUS_COLOR.get(sm["status"], "dim"))
        self.say(f"  Status : {colour('● ' + sm['status'])}  {sm['status_detail']}")
        self.say(f"  Trend  : {sm['trend']}")
        self.say("")
        pairs = [
            ("Period", f"{sm['first_date']} → {sm['last_date']}"),
            ("Total focused time", f"{fmt_minutes(sm['total_minutes'])} ({sm['total_minutes']} min)"),
            ("Sessions / pomodoros", f"{sm['total_sessions']} / {sm['total_pomodoros']}"),
            ("Active days", sm["active_days"]),
            ("Average per session", f"{sm['avg_session']} min"),
            ("Average per active day", f"{sm['avg_per_active_day']} min"),
            ("Longest session", f"{sm['longest_session']['minutes']} min · {sm['longest_session']['subject']} · {sm['longest_session']['date']}"),
            ("Best day", f"{sm['best_day']['minutes']} min on {sm['best_day']['date']}"),
            ("Top subject", f"{sm['top_subject']['subject']} ({sm['top_subject']['share']}%)"),
            ("Streak (current / best)", f"{sm['current_streak']} / {sm['longest_streak']} day(s)"),
            ("Last 7 vs previous 7", f"{sm['last7']} vs {sm['prev7']} min"),
            ("Today", f"{sm['today_minutes']} / {sm['daily_goal']} min goal"),
        ]
        for k, v in pairs:
            self.say(f"  {k:<26}{v}")
        self.heading("FOCUSED MINUTES BY SUBJECT")
        self.table(sm["by_subject"], [("Subject", "subject", 22, "<"), ("Minutes", "minutes", 7, ">"),
                                      ("Sessions", "sessions", 8, ">"), ("Pomos", "pomodoros", 5, ">"),
                                      ("Avg", "avg_session", 6, ">"), ("Share %", "share", 7, ">")])
        self.say("")
        for line in text_bar_chart(sm["by_subject"]):
            self.say("  " + self.st.red(line))
        self.heading("LAST 14 DAYS")
        totals = daily_totals(self.storage.sessions)
        days = [(self.today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        peak = max([totals.get(d, 0) for d in days] + [1])
        for d in days:
            m = totals.get(d, 0)
            bar = "▇" * round(30 * m / peak)
            self.say(f"  {d[5:]} {bar:<30} {m if m else self.st.dim('-')}")
        self.say(self.st.dim("\n  Tip: use option 6 to export a PNG chart and full reports."))

    # ------------------------------------------------------ 5. warnings
    def show_warnings(self) -> None:
        self.heading("WARNINGS & ALERTS")
        warns = get_warnings(self.storage.sessions, self.today, self.storage.settings)
        icons = {"CRITICAL": self.st.red("✖ CRITICAL"), "WARNING": self.st.yellow("▲ WARNING "),
                 "INFO": self.st.cyan("ℹ INFO    ")}
        for w in warns:
            self.say(f"  {icons[w.level]}  {w.message}")
        crit = sum(w.level == "CRITICAL" for w in warns)
        self.say(self.st.dim(f"\n  {len(warns)} flag(s), {crit} critical."))

    # ------------------------------------------------------- 6. export
    def export(self) -> None:
        self.heading("EXPORT REPORTS")
        if not self.storage.sessions:
            self.say(self.st.yellow("  Nothing to export yet - log a session first."))
            return
        paths = export_all(self.storage.sessions, self.export_dir, self.today, self.storage.settings)
        for p in paths:
            self.say(self.st.green(f"  ✓ {p}"))
        if not any(p.suffix == ".png" for p in paths):
            self.say(self.st.yellow("  (Chart skipped: install matplotlib with `pip install matplotlib`.)"))

    # ------------------------------------------------------- 7. import
    def bulk_import(self) -> None:
        self.heading("BULK IMPORT FROM CSV  (q = cancel)")
        self.say(self.st.dim("  Required columns: date, subject, focused_minutes."
                             " Optional: pomodoros, break_minutes, notes."))
        self.say(self.st.dim("  Try data/sample_sessions.csv or data/dirty_import.csv"))
        path = self.ask("CSV file path", lambda v: self._nonblank(v, "File path"))
        if path is None: return self.cancelled()
        path = path.strip().strip('"').strip("'")
        log = Path(self.export_dir) / "import_errors.log"
        res = import_csv_file(path, self.storage, log, self.today)
        colour = self.st.red if res.fatal else (self.st.yellow if res.errors else self.st.green)
        self.say(colour("  " + res.summary_line()))
        for row, reason in res.errors[:12]:
            self.say(self.st.red(f"    row {row}: ") + reason)
        if len(res.errors) > 12:
            self.say(self.st.dim(f"    … and {len(res.errors) - 12} more"))
        if res.log_path:
            self.say(self.st.dim(f"  Full row-by-row error log: {res.log_path}"))

    @staticmethod
    def _nonblank(v: str, label: str) -> str:
        if not str(v).strip():
            raise ValidationError(f"{label} cannot be blank.")
        return str(v)

    # -------------------------------------------------------- 8. delete
    def delete_session(self) -> None:
        self.heading("DELETE A SESSION  (q = cancel)")
        if not self.storage.sessions:
            self.say(self.st.yellow("  No sessions to delete."))
            return
        sid = self.ask("Session ID", lambda v: parse_int(v, "Session ID", 1, 10**9))
        if sid is None: return self.cancelled()
        target = next((s for s in self.storage.sessions if s.id == sid), None)
        if target is None:
            self.say(self.st.red(f"  ✗ No session with ID {sid}."))
            return
        self.say(f"  #{target.id} {target.date} · {target.subject} · {target.focused_minutes} min · {target.notes}")
        if self.confirm("Really delete this session?"):
            self.storage.delete(sid)
            self.say(self.st.green("  ✓ Deleted."))
        else:
            self.cancelled()

    # ------------------------------------------------------- 9. settings
    def settings(self) -> None:
        self.heading("SETTINGS  (Enter keeps the current value)")
        cfg = self.storage.settings
        goal = self.ask("Daily goal (minutes)", lambda v: parse_int(v, "Daily goal", 10, 480), cfg["daily_goal"])
        if goal is None: return self.cancelled()
        limit = self.ask("Daily warning limit (minutes)",
                         lambda v: parse_int(v, "Daily limit", max(goal, 30), 1440), cfg["daily_limit"])
        if limit is None: return self.cancelled()
        anomaly = self.ask("Flag single sessions of at least (minutes)",
                           lambda v: parse_int(v, "Anomaly threshold", 30, 480), cfg["anomaly_session"])
        if anomaly is None: return self.cancelled()
        inactive = self.ask("Warn after N inactive days", lambda v: parse_int(v, "Inactive days", 1, 60),
                            cfg["inactive_days"])
        if inactive is None: return self.cancelled()
        self.storage.update_settings(daily_goal=goal, daily_limit=limit,
                                     anomaly_session=anomaly, inactive_days=inactive)
        self.say(self.st.green("  ✓ Settings saved."))
