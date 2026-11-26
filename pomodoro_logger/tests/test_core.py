"""Unit + end-to-end tests (standard library only).  Run:  python -m unittest -v"""
import csv
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate_sample_data import DIRTY, build                         # noqa: E402
from pomodoro import validation as v                                   # noqa: E402
from pomodoro.export import (export_all, render_audit_text, render_markdown,  # noqa: E402
                             render_sessions_csv, render_subject_csv)
from pomodoro.importer import import_csv_file, import_csv_text          # noqa: E402
from pomodoro.logic import (daily_totals, minutes_by_subject, record_session,  # noqa: E402
                            search, weekly_totals)
from pomodoro.storage import Storage                                   # noqa: E402
from pomodoro.summary import build_summary, current_streak, longest_streak  # noqa: E402
from pomodoro.ui_cli import CLI                                        # noqa: E402
from pomodoro.warnings_ import get_warnings                            # noqa: E402

TODAY = date(2026, 11, 25)


def make_storage(tmp):
    return Storage(Path(tmp) / "s.json")


def raw(**kw):
    base = dict(date="2026-11-24", subject="math", focused_minutes="50", pomodoros="2",
                break_minutes="5", notes="")
    base.update(kw)
    return base


class TestValidation(unittest.TestCase):
    def test_minutes_boundaries(self):
        self.assertEqual(v.validate_minutes("1"), 1)
        self.assertEqual(v.validate_minutes("480"), 480)
        self.assertEqual(v.validate_minutes(" 45.0 "), 45)
        for bad in ["0", "481", "-5", "", "  ", "abc", "4.5", "1e3", "NaN", None]:
            with self.assertRaises(v.ValidationError, msg=repr(bad)):
                v.validate_minutes(bad)

    def test_date(self):
        self.assertEqual(v.validate_date("2026-11-25", TODAY), "2026-11-25")
        for bad in ["", "25/11/2026", "2026-02-30", "2026-11-26", "1999-01-01", "2026-1-1", "xx"]:
            with self.assertRaises(v.ValidationError, msg=bad):
                v.validate_date(bad, TODAY)

    def test_subject_normalised_and_sanitised(self):
        self.assertEqual(v.validate_subject("  mATH   tricks "), "Math Tricks")
        self.assertEqual(v.validate_subject("AI basics"), "AI Basics")
        for bad in ["", "a", "x" * 41, "<script>", "-dash", "tab\x00"[:0]]:
            with self.assertRaises(v.ValidationError, msg=repr(bad)):
                v.validate_subject(bad)

    def test_notes_and_control_chars(self):
        self.assertEqual(v.validate_notes("a\x07b\n c"), "a b c")
        with self.assertRaises(v.ValidationError):
            v.validate_notes("x" * 201)

    def test_cross_field(self):
        with self.assertRaises(v.ValidationError):
            v.validate_session_fields(raw(focused_minutes="200", pomodoros="1"), TODAY)
        with self.assertRaises(v.ValidationError):
            v.validate_session_fields(raw(focused_minutes="3", pomodoros="5"), TODAY)
        ok = v.validate_session_fields(raw(pomodoros=""), TODAY)       # blank -> derived
        self.assertEqual(ok["pomodoros"], 2)

    def test_all_errors_collected(self):
        with self.assertRaises(v.ValidationError) as cm:
            v.validate_session_fields(raw(date="bad", subject="", focused_minutes="x"), TODAY)
        self.assertEqual(str(cm.exception).count(" | "), 2)

    def test_ask_retries_until_valid_and_cancels(self):
        answers = iter(["", "abc", "0", "30"])
        out = []
        self.assertEqual(v.ask("m", v.validate_minutes, input_fn=lambda p: next(answers),
                               print_fn=lambda *a: out.append(a)), 30)
        self.assertEqual(len(out), 3)
        self.assertIsNone(v.ask("m", v.validate_minutes, input_fn=lambda p: "q"))

        def eof(_):
            raise EOFError
        self.assertIsNone(v.ask("m", v.validate_minutes, input_fn=eof, print_fn=lambda *a: None))


class TestStorage(unittest.TestCase):
    def test_missing_file_creates_template(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            self.assertEqual(st.sessions, [])
            self.assertTrue(st.path.exists())
            self.assertTrue(any("created a fresh" in n for n in st.load_notes))

    def test_corrupt_file_backed_up(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.json"
            p.write_text("{not json", encoding="utf-8")
            st = Storage(p)
            self.assertEqual(st.sessions, [])
            self.assertEqual(len(list(Path(t).glob("*.bak"))), 1)
            self.assertEqual(json.loads(p.read_text())["sessions"], [])

    def test_wrong_structure_and_binary(self):
        with tempfile.TemporaryDirectory() as t:
            for payload in [b"[]", b'{"sessions": 5}', b"\xff\xfe\x00bad", b""]:
                p = Path(t) / "x.json"
                p.write_bytes(payload)
                self.assertEqual(Storage(p).sessions, [])

    def test_invalid_records_dropped_but_valid_kept(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.json"
            good = dict(id=1, date="2026-11-01", subject="Math", focused_minutes=30, pomodoros=2,
                        break_minutes=5, notes="", created_at="x")
            bad = dict(good, id=2, focused_minutes=9999)
            dup = dict(good)
            p.write_text(json.dumps({"sessions": [good, bad, dup, "junk"], "settings": {"daily_goal": "x"}}))
            st = Storage(p)
            self.assertEqual([s.id for s in st.sessions], [1])
            self.assertEqual(st.next_id, 2)
            self.assertEqual(st.settings["daily_goal"], 120)

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            s = record_session(st, raw(), TODAY)
            st2 = make_storage(t)                                  # "restart"
            self.assertEqual(len(st2.sessions), 1)
            self.assertEqual(st2.sessions[0].subject, "Math")
            self.assertEqual(st2.next_id, s.id + 1)
            st2.update_settings(daily_goal=90)
            self.assertEqual(make_storage(t).settings["daily_goal"], 90)

    def test_delete_and_ids_not_reused(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            a = record_session(st, raw(), TODAY)
            self.assertTrue(st.delete(a.id))
            self.assertFalse(st.delete(a.id))
            b = record_session(st, raw(), TODAY)
            self.assertGreater(b.id, a.id)


class TestLogicAndSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = make_storage(self.tmp.name)
        rows = [("2026-11-25", "math", 60, 3, "algebra"), ("2026-11-25", "physics", 30, 2, "optics lab"),
                ("2026-11-24", "math", 90, 4, "calculus"), ("2026-11-23", "history", 45, 2, ""),
                ("2026-11-15", "math", 120, 5, "old"), ]
        for d, s, m, p, n in rows:
            record_session(self.st, raw(date=d, subject=s, focused_minutes=m, pomodoros=p, notes=n), TODAY)

    def tearDown(self):
        self.tmp.cleanup()

    def test_minutes_by_subject(self):
        rows = minutes_by_subject(self.st.sessions)
        self.assertEqual(rows[0]["subject"], "Math")
        self.assertEqual(rows[0]["minutes"], 270)
        self.assertEqual(rows[0]["sessions"], 3)
        self.assertEqual(sum(r["minutes"] for r in rows), 345)
        self.assertAlmostEqual(sum(r["share"] for r in rows), 100, delta=0.2)

    def test_daily_weekly(self):
        self.assertEqual(daily_totals(self.st.sessions)["2026-11-25"], 90)
        self.assertEqual(sum(weekly_totals(self.st.sessions).values()), 345)

    def test_search(self):
        s = self.st.sessions
        self.assertEqual(len(search(s, keyword="OPTICS")), 1)             # notes, case-insens.
        self.assertEqual(len(search(s, subject="math")), 3)
        self.assertEqual(len(search(s, date_from="2026-11-24")), 3)
        self.assertEqual(len(search(s, min_minutes=60, max_minutes=100)), 2)
        self.assertEqual(len(search(s, keyword="zzz")), 0)
        self.assertEqual(search(s, sort_by="minutes")[0].focused_minutes, 120)
        self.assertEqual(search(s, sort_by="minutes", descending=False)[0].focused_minutes, 30)

    def test_summary(self):
        sm = build_summary(self.st.sessions, TODAY, 120)
        self.assertEqual(sm["total_minutes"], 345)
        self.assertEqual(sm["active_days"], 4)
        self.assertEqual(sm["current_streak"], 3)
        self.assertEqual(sm["last7"], 225)
        self.assertEqual(sm["prev7"], 120)
        self.assertEqual(sm["top_subject"]["subject"], "Math")
        self.assertEqual(sm["longest_session"]["minutes"], 120)
        self.assertIn("Improving", sm["trend"])
        self.assertEqual(sm["status"], "BEHIND")          # 225/7 = 32 min/day vs 120 goal

    def test_empty_summary(self):
        sm = build_summary([], TODAY)
        self.assertEqual(sm["status"], "NO DATA")
        self.assertEqual(sm["total_minutes"], 0)

    def test_streak_helpers(self):
        days = {TODAY - timedelta(days=i) for i in (1, 2, 3, 6, 7)}
        self.assertEqual(current_streak(days, TODAY), 3)       # today empty -> counts from yesterday
        self.assertEqual(current_streak({TODAY - timedelta(days=5)}, TODAY), 0)
        self.assertEqual(longest_streak(days), 3)


class TestWarnings(unittest.TestCase):
    def test_flags(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            record_session(st, raw(date="2026-11-10", focused_minutes="480", pomodoros="8"), TODAY)
            record_session(st, raw(date="2026-11-10", focused_minutes="90", pomodoros="4"), TODAY)
            record_session(st, raw(date="2026-11-12", focused_minutes="40", pomodoros="6"), TODAY)
            for _ in range(2):
                record_session(st, raw(date="2026-11-13", focused_minutes="10", pomodoros="1", break_minutes="20"), TODAY)
            record_session(st, raw(date="2026-11-14", focused_minutes="2", pomodoros="1"), TODAY)
            codes = {w.code for w in get_warnings(st.sessions, TODAY, st.settings)}
            for expected in ["DAILY_LIMIT", "LONG_SESSION", "RATIO", "DUPLICATE", "BREAKS",
                             "SHORT_SESSION", "INACTIVE", "GOAL_SHORTFALL", "TODAY_GOAL"]:
                self.assertIn(expected, codes)
            self.assertEqual(get_warnings(st.sessions, TODAY, st.settings)[0].level, "CRITICAL")

    def test_no_data(self):
        self.assertEqual(get_warnings([], TODAY)[0].code, "NO_DATA")


class TestImport(unittest.TestCase):
    def dirty_text(self):
        end = TODAY
        dd = lambda o: (end - timedelta(days=o)).isoformat()
        return DIRTY.format(d0=dd(2), d1=dd(1), d2=dd(7), d3=dd(8), d4=dd(10),
                            future=(end + timedelta(days=30)).isoformat())

    def test_dirty_csv_row_by_row(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            res = import_csv_text(self.dirty_text(), st, TODAY)
            self.assertEqual((res.total_rows, res.imported, res.duplicates, res.rejected), (18, 5, 1, 12))
            self.assertEqual(len(st.sessions), 5)
            self.assertEqual(len(make_storage(t).sessions), 5)          # persisted once
            lines = {r for r, _ in res.errors}
            self.assertTrue({4, 5, 6, 7}.issubset(lines))               # line numbers reported

    def test_import_file_writes_log_and_handles_bad_inputs(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            p = Path(t) / "d.csv"
            p.write_text(self.dirty_text(), encoding="utf-8")
            log = Path(t) / "e.log"
            res = import_csv_file(p, st, log, TODAY)
            self.assertTrue(log.exists() and "Row 4" in log.read_text())
            self.assertEqual(res.log_path, log)
            self.assertIn("not found", import_csv_file(Path(t) / "nope.csv", st, log).fatal)
            self.assertIn("missing required", import_csv_text("a,b\n1,2\n", st).fatal)
            self.assertIn("empty", import_csv_text("", st).fatal)
            self.assertIn("duplicate column", import_csv_text("date,subject,date,minutes\n", st).fatal)
            self.assertTrue(import_csv_file(t, st, log).fatal)           # directory

    def test_semicolon_bom_and_latin1(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            text = "\ufeffdate;subject;minutes\n2026-11-20;Math;30\n"
            self.assertEqual(import_csv_text(text, st, TODAY).imported, 1)
            p = Path(t) / "l.csv"
            p.write_bytes("date,subject,minutes,notes\n2026-11-21,Math,30,caf\xe9\n".encode("latin-1"))
            self.assertEqual(import_csv_file(p, st, Path(t) / "x.log", TODAY).imported, 1)

    def test_sample_dataset(self):
        rows = build(TODAY)
        self.assertEqual(len(rows), 40)
        with tempfile.TemporaryDirectory() as t:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
            st = make_storage(t)
            res = import_csv_text(buf.getvalue(), st, TODAY)
            self.assertEqual(res.rejected, 0)
            self.assertEqual(res.imported + res.duplicates, 40)
            self.assertEqual(res.duplicates, 1)                         # the planted duplicate


class TestExport(unittest.TestCase):
    def test_all_formats(self):
        with tempfile.TemporaryDirectory() as t:
            st = make_storage(t)
            for r in build(TODAY):
                try:
                    record_session(st, r, TODAY)
                except v.ValidationError:
                    self.fail("sample row invalid")
            sm = build_summary(st.sessions, TODAY)
            wn = get_warnings(st.sessions, TODAY, st.settings)
            md = render_markdown(st.sessions, sm, wn)
            self.assertIn("## Focused Minutes by Subject", md)
            self.assertIn("## Warnings", md)
            txt = render_audit_text(st.sessions, sm, wn)
            self.assertIn("SHA-256", txt)
            rows = list(csv.reader(io.StringIO(render_sessions_csv(st.sessions))))
            self.assertEqual(len(rows), 41)                              # header + 40
            self.assertEqual(rows[0][0], "id")
            self.assertEqual(len(list(csv.reader(io.StringIO(render_subject_csv(st.sessions))))),
                             len(sm["by_subject"]) + 1)
            paths = export_all(st.sessions, Path(t) / "out", TODAY, st.settings)
            suffixes = {p.suffix for p in paths}
            self.assertTrue({".md", ".txt", ".csv"}.issubset(suffixes))
            self.assertTrue(all(p.stat().st_size > 0 for p in paths))


class TestCLIFlow(unittest.TestCase):
    """Scripted end-to-end journey exactly like the brief's demo."""

    def run_cli(self, path, answers, export_dir):
        feed = iter(answers)
        out = []
        cli = CLI(Storage(path), str(export_dir), input_fn=lambda p: (out.append(p), next(feed))[1],
                  print_fn=lambda *a: out.append(" ".join(map(str, a))), color=False, today=TODAY)
        self.assertEqual(cli.run(), 0)
        return "\n".join(out)

    def test_demo_journey(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "s.json"
            text = self.run_cli(path, [
                "1",                                  # log session
                "25/11/2026", "2026-11-25",           # bad date -> corrected
                "calculus",
                "", "abc", "999", "50",               # blank / text / out-of-range -> 50
                "0", "2",                             # pomodoros 0 out of range -> 2
                "", "chain rule", "y",                # break default, notes, confirm
                "99", "x",                            # invalid menu options
                "4", "", "5", "", "6", "", "0"], Path(t) / "ex")
            self.assertIn("must use the format YYYY-MM-DD", text)
            self.assertIn("cannot be blank", text)
            self.assertIn("must be a whole number", text)
            self.assertIn("must be between 1 and 480", text)
            self.assertIn("Saved as session #1", text)
            self.assertIn("'99' is not a valid option", text)
            self.assertIn("EXECUTIVE SUMMARY", text)
            self.assertIn("Calculus", text)
            # restart -> persistence
            text2 = self.run_cli(path, ["2", "0"], Path(t) / "ex")
            self.assertIn("1 session loaded", text2)
            self.assertIn("chain rule", text2)
            self.assertTrue(list((Path(t) / "ex").glob("*.md")))

    def test_survives_eof_and_import_flow(self):
        with tempfile.TemporaryDirectory() as t:
            dirty = Path(t) / "d.csv"
            dirty.write_text(TestImport().dirty_text(), encoding="utf-8")
            text = self.run_cli(Path(t) / "s.json", ["7", str(dirty), "5", "8", "1", "y", "3",
                                                     "calculus", "", "", "", "", "", "date", "0"], Path(t) / "ex")
            self.assertIn("5 imported", text)
            self.assertIn("rejected", text)
            self.assertTrue((Path(t) / "ex" / "import_errors.log").exists())
        # input stream ending abruptly must exit cleanly rather than crash
        with tempfile.TemporaryDirectory() as t:
            def eof(_):
                raise EOFError
            cli = CLI(Storage(Path(t) / "s.json"), t, input_fn=eof, print_fn=lambda *a: None,
                      color=False, today=TODAY)
            self.assertEqual(cli.run(), 0)


if __name__ == "__main__":
    unittest.main()
