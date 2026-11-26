# 🍅 Pomodoro Study Session Logger  (Project #103 · GreenFuture Hack)

Record study sessions, summarise **focused minutes by subject**, and get clear
insights — in a zero-dependency terminal app, with an optional modern **Streamlit** GUI.

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
python main.py                  # terminal UI - standard library only, Python 3.10+
```
Optional GUI + charts:
```bash
pip install -r requirements.txt
python main.py --gui            # or: streamlit run app_gui.py
```
Other switches: `--seed` (reload the 40-session sample), `--data FILE`, `--exports DIR`.
Regenerate sample data with dates ending today: `python generate_sample_data.py --load`.

## Brief → feature map
| Requirement | Where |
|---|---|
| Menu-driven terminal interface | `pomodoro/ui_cli.py` - branded welcome, numbered menu, ANSI colour (honours `NO_COLOR`) |
| Defensive input validation | `pomodoro/validation.py` - one validator per field, `ask()` loops until valid; GUI uses the same rules |
| Core logic (minutes by subject) | `pomodoro/logic.py` - `record_session`, `minutes_by_subject`, daily/weekly rollups |
| Local persistence (JSON) | `pomodoro/storage.py` - atomic writes, corrupt/missing file recovery (backup + fresh template), bad records dropped |
| Query & search | menu 3 / GUI "Browse & Search": keyword (subject+notes), category, date range, min/max minutes, sort |
| Executive summary | menu 4 / Dashboard: totals, averages, top subject, longest session, streaks, 7-vs-7-day trend, status indicator |
| **Stretch:** multi-format export | menu 6 / Reports: Markdown, text audit log (SHA-256), sessions CSV, subject-summary CSV, PNG chart |
| **Stretch:** threshold warnings | menu 5 / Reports: daily-limit breach, long/short/inconsistent sessions, duplicates, inactivity, goal shortfall |
| **Stretch:** GUI | `app_gui.py` (Streamlit): dashboard, log form, search table, reports, CSV import, settings |
| **Stretch:** bulk import | menu 7 / Import page: header aliases, per-row validation, duplicate skipping, `exports/import_errors.log` |

## Validation rules
Date `YYYY-MM-DD`, real, not future · Subject 2-40 chars, safe characters, normalised (`math` → `Math`) ·
Focused minutes whole number 1-480 · Pomodoros 1-20 (blank = auto from 25-min blocks) ·
Break 0-240 · Notes ≤ 200 chars, control characters stripped ·
Cross-check: minutes must fit the pomodoro count (≤ 90 min each, ≥ 1 min each).

## Suggested demo (matches the brief)
1. `python main.py --seed` → branded welcome screen and menu.
2. Option **1**: type a bad date (`25/11/2026`), blank / `abc` / `999` minutes - watch each get caught - then save a valid entry.
3. Option **4**: summary tables, bars, trend and status. Option **5**: warnings (the seed data trips most of them).
4. Option **7** with `data/dirty_import.csv`: 5 rows imported, 12 rejected with row-by-row reasons.
5. Exit, relaunch → data is still there. Option **6** → report files + chart in `exports/`.
6. `python main.py --gui` to show the web interface.

## Data files
`data/sample_sessions.csv|json` (40 sessions incl. boundary values 1 and 480 min, a 780-min day, duplicate,
ratio anomaly, quotes/commas in notes) · `data/dirty_import.csv` (bad dates, text, out-of-range, wrong column counts, unsafe characters, …) ·
`data/sessions.json` (live data, pre-seeded).

## Tests
```bash
python -m unittest discover -s tests -t . -v      # 28 tests, no dependencies
```
Covers validation, corrupt-file recovery, persistence round-trip, aggregation maths, search, summary, warnings,
dirty-CSV import, all export formats, and a scripted CLI journey (bad input → fix → save → restart → export).

## Layout
```
main.py  app_gui.py  generate_sample_data.py
pomodoro/ models · validation · storage · logic · summary · warnings_ · export · importer · ui_cli
data/  exports/  tests/test_core.py
sample_exports/   example generated reports (Markdown, audit log, CSVs, chart, import error log)
docs/             recorded terminal demo transcripts (validation catch, summary, import, restart persistence)
```


## Version 1.1 upgrades
- **Explainable insights:** dashboard observations based on recent sessions, subject distribution and subjects not recently logged; no opaque model or external data.
- **Architecture/config:** configuration and logging defaults centralized in `pomodoro/config.py`; log level can be controlled with `POMODORO_LOG_LEVEL`.
- **Packaging metadata:** `pyproject.toml` enables standard Python package tooling.
- **Continuous integration:** GitHub Actions runs the unittest suite on Python 3.10, 3.11 and 3.12 for pushes and pull requests.
- **Expanded regression tests:** 3 tests cover insight generation and edge cases; 31 tests currently pass.

Run checks locally with `python -m unittest discover -v`. CI is configured but its hosted runs require pushing the project to GitHub.
