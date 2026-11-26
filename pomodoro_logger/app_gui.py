"""Streamlit GUI for the Pomodoro Study Session Logger.

Run with:   streamlit run app_gui.py      (or)      python main.py --gui
Needs:      pip install streamlit pandas matplotlib
It reuses the same validation / storage / summary code as the terminal app.
"""
from __future__ import annotations

import argparse
import io
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pomodoro import APP_NAME                                         # noqa: E402
from pomodoro.export import (export_all, render_audit_text, render_markdown,   # noqa: E402
                             render_sessions_csv, render_subject_csv, save_chart)
from pomodoro.importer import _decode, import_csv_file, import_csv_text, write_error_log  # noqa: E402
from pomodoro.logic import (daily_totals, fmt_minutes, minutes_by_subject,       # noqa: E402
                            record_session, search, subjects as list_subjects, weekly_totals)
from pomodoro.models import (MAX_BREAK, MAX_FOCUS, MAX_POMO, DEFAULT_SETTINGS)    # noqa: E402
from pomodoro.storage import Storage                                   # noqa: E402
from pomodoro.summary import build_summary                             # noqa: E402
from pomodoro.insights import build_insights                           # noqa: E402
from pomodoro.validation import ValidationError, validate_session_fields  # noqa: E402
from pomodoro.warnings_ import get_warnings                            # noqa: E402


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "sessions.json"))
    ap.add_argument("--exports", default=str(ROOT / "exports"))
    return ap.parse_known_args(sys.argv[1:])[0]


ARGS = _args()
TODAY = date.today()

st.set_page_config(page_title=APP_NAME, page_icon="🍅", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
div[data-testid="stMetric"] {background: rgba(128,128,128,0.08); border: 1px solid rgba(128,128,128,0.18);
    border-radius: 14px; padding: 14px 18px;}
.status-pill {display:inline-block; padding: 6px 16px; border-radius: 999px; font-weight: 700; color: #fff;}
.hero {font-size: 2rem; font-weight: 800; letter-spacing: -0.5px;}
.sub {opacity: .7; margin-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)

storage = Storage(ARGS.data)
cfg = storage.settings
sessions = storage.sessions
STATUS_COLORS = {"ON TRACK": "#2f9e6e", "NEEDS FOCUS": "#d9a400", "BEHIND": "#e5484d",
                 "INACTIVE": "#e5484d", "NO DATA": "#6b7280"}


def sessions_df(rows) -> pd.DataFrame:
    cols = ["id", "date", "subject", "focused_minutes", "pomodoros", "break_minutes", "notes"]
    return pd.DataFrame([{c: getattr(s, c) for c in cols} for s in rows], columns=cols)


# ------------------------------------------------------------------ sidebar
st.sidebar.markdown("## 🍅 Pomodoro Logger")
page = st.sidebar.radio("Navigate", ["Dashboard", "Log Session", "Browse & Search",
                                      "Reports", "Import"], label_visibility="collapsed")
st.sidebar.caption(f"{len(sessions)} sessions · data: {Path(ARGS.data).name}")
for note in storage.load_notes:
    st.sidebar.warning(note)

with st.sidebar.expander("⚙️ Settings"):
    goal = st.number_input("Daily goal (min)", 10, 480, int(cfg["daily_goal"]))
    limit = st.number_input("Daily warning limit (min)", 30, 1440, int(cfg["daily_limit"]))
    anomaly = st.number_input("Flag single sessions ≥ (min)", 30, 480, int(cfg["anomaly_session"]))
    inactive = st.number_input("Warn after N inactive days", 1, 60, int(cfg["inactive_days"]))
    if st.button("Save settings"):
        if limit < goal:
            st.error("The daily limit must be at least the daily goal.")
        else:
            storage.update_settings(daily_goal=goal, daily_limit=limit,
                                    anomaly_session=anomaly, inactive_days=inactive)
            st.success("Settings saved.")
            cfg = storage.settings

st.markdown(f'<div class="hero">🍅 {APP_NAME}</div>', unsafe_allow_html=True)
st.markdown('<div class="sub">Track focused minutes by subject, stay on target, build a streak.</div>',
            unsafe_allow_html=True)

# ---------------------------------------------------------------- Dashboard
if page == "Dashboard":
    sm = build_summary(sessions, TODAY, cfg["daily_goal"])
    st.subheader("Data-driven study insights")
    for insight in build_insights(sessions, TODAY):
        st.markdown(f"**{insight["title"]}**\n\n{insight["detail"]}")
    if not sm["total_sessions"]:
        st.info("No sessions yet - head to **Log Session** or **Import** to get started.")
    else:
        color = STATUS_COLORS.get(sm["status"], "#6b7280")
        st.markdown(f'<span class="status-pill" style="background:{color}">{sm["status"]}</span> '
                    f'&nbsp; {sm["status_detail"]} &nbsp;·&nbsp; **Trend:** {sm["trend"]}',
                    unsafe_allow_html=True)
        st.write("")
        c = st.columns(4)
        c[0].metric("Total focused time", fmt_minutes(sm["total_minutes"]), f'{sm["total_sessions"]} sessions')
        c[1].metric("Avg / session", f'{sm["avg_session"]} min')
        c[2].metric("Avg / active day", f'{sm["avg_per_active_day"]} min', f'{sm["active_days"]} days')
        c[3].metric("Streak", f'{sm["current_streak"]} day(s)', f'best {sm["longest_streak"]}')
        c = st.columns(4)
        ts, ls = sm["top_subject"], sm["longest_session"]
        c[0].metric("Top subject", ts["subject"], f'{ts["share"]}% of time')
        c[1].metric("Longest session", f'{ls["minutes"]} min', ls["subject"])
        delta = sm["last7"] - sm["prev7"]
        c[2].metric("Last 7 days", f'{sm["last7"]} min', f"{delta:+} vs previous 7")
        c[3].metric("Today", f'{sm["today_minutes"]} min', f'goal {sm["daily_goal"]}')

        left, right = st.columns(2)
        subj_df = pd.DataFrame(sm["by_subject"])
        with left:
            st.subheader("Focused minutes by subject")
            st.bar_chart(subj_df.set_index("subject")[["minutes"]])
        with right:
            st.subheader("Daily trend (last 30 days)")
            totals = daily_totals(sessions)
            days = [(TODAY - timedelta(days=i)) for i in range(29, -1, -1)]
            trend = pd.DataFrame({"minutes": [totals.get(d.isoformat(), 0) for d in days]},
                                 index=pd.to_datetime(days))
            st.line_chart(trend)
        st.subheader("Subject breakdown")
        st.dataframe(subj_df.rename(columns={"subject": "Subject", "minutes": "Minutes",
                                             "sessions": "Sessions", "pomodoros": "Pomodoros",
                                             "avg_session": "Avg session (min)", "share": "Share %"}),
                     hide_index=True)
        st.subheader("Weekly totals")
        wk = weekly_totals(sessions)
        st.bar_chart(pd.DataFrame({"minutes": list(wk.values())}, index=list(wk.keys())))
        warns = get_warnings(sessions, TODAY, cfg)
        crit = [w for w in warns if w.level == "CRITICAL"]
        if crit:
            st.error(f"{len(crit)} critical warning(s) - see the **Reports** page.")

# -------------------------------------------------------------- Log Session
elif page == "Log Session":
    st.subheader("Log a study session")
    known = list_subjects(sessions)
    if known:
        st.caption("Known subjects: " + ", ".join(known))
    with st.form("log_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        d = c1.date_input("Date", value=TODAY, max_value=TODAY)
        subject = c2.text_input("Subject", placeholder="e.g. Mathematics")
        c3, c4, c5 = st.columns(3)
        minutes = c3.number_input(f"Focused minutes (1-{MAX_FOCUS})", 0, 2000, 25, step=5)
        pomos = c4.number_input(f"Pomodoros (1-{MAX_POMO}, 0 = auto)", 0, 100, 0)
        brk = c5.number_input(f"Break minutes (0-{MAX_BREAK})", 0, 2000, 0, step=5)
        notes = st.text_area("Notes (optional, max 200 characters)")
        submitted = st.form_submit_button("Save session", type="primary")
    if submitted:
        raw = {"date": d.isoformat() if isinstance(d, date) else str(d), "subject": subject,
               "focused_minutes": minutes, "pomodoros": "" if pomos == 0 else pomos,
               "break_minutes": brk, "notes": notes}
        try:
            validate_session_fields(raw, TODAY)          # show *all* problems at once
        except ValidationError as exc:
            for msg in str(exc).split(" | "):
                st.error(msg)
        else:
            s = record_session(storage, raw, TODAY)
            st.success(f"Saved session #{s.id}: {s.subject} - {s.focused_minutes} min on {s.date}.")
            day_total = daily_totals(storage.sessions)[s.date]
            if day_total > cfg["daily_limit"]:
                st.warning(f"{s.date} now totals {day_total} min, above your {cfg['daily_limit']} min limit.")
            else:
                st.caption(f"{s.date} total so far: {fmt_minutes(day_total)}")

# --------------------------------------------------------- Browse & Search
elif page == "Browse & Search":
    st.subheader("Browse & search")
    c1, c2, c3 = st.columns(3)
    kw = c1.text_input("Keyword (subject or notes)")
    subj = c2.selectbox("Subject", ["All"] + list_subjects(sessions))
    sort_by = c3.selectbox("Sort by", ["date", "subject", "minutes", "pomodoros"])
    c4, c5, c6 = st.columns(3)
    use_dates = c4.checkbox("Filter by date range")
    rng = c4.date_input("Date range", value=(TODAY - timedelta(days=30), TODAY), max_value=TODAY) if use_dates else ()
    mn, mx = c5.slider("Focused minutes", 0, MAX_FOCUS, (0, MAX_FOCUS))
    desc = c6.toggle("Descending", value=True)
    dfrom = dto = None
    if use_dates and isinstance(rng, (tuple, list)) and len(rng) == 2:
        dfrom, dto = rng[0].isoformat(), rng[1].isoformat()
    found = search(sessions, kw, "" if subj == "All" else subj, dfrom, dto,
                   mn if mn > 0 else None, mx if mx < MAX_FOCUS else None, sort_by, desc)
    st.caption(f"{len(found)} result(s) · {sum(s.focused_minutes for s in found)} focused minutes")
    if found:
        st.dataframe(sessions_df(found), hide_index=True)
        st.download_button("⬇ Download results (CSV)", render_sessions_csv(found),
                           "filtered_sessions.csv", "text/csv")
    else:
        st.info("No sessions match these filters.")
    with st.expander("🗑 Delete a session"):
        if sessions:
            sid = st.selectbox("Session", [s.id for s in sorted(sessions, key=lambda x: x.date, reverse=True)],
                               format_func=lambda i: next(f"#{s.id} · {s.date} · {s.subject} · {s.focused_minutes} min"
                                                          for s in sessions if s.id == i))
            sure = st.checkbox("Yes, delete this session permanently")
            if st.button("Delete", disabled=not sure):
                storage.delete(sid)
                st.success(f"Deleted session #{sid}. Refresh the page (R) to update the table.")
        else:
            st.caption("Nothing to delete.")

# ------------------------------------------------------------------ Reports
elif page == "Reports":
    st.subheader("Warnings")
    warns = get_warnings(sessions, TODAY, cfg)
    for w in warns:
        {"CRITICAL": st.error, "WARNING": st.warning, "INFO": st.info}[w.level](f"**{w.code}** - {w.message}")
    st.subheader("Export")
    if not sessions:
        st.info("Log or import some sessions to enable exports.")
    else:
        sm = build_summary(sessions, TODAY, cfg["daily_goal"])
        c = st.columns(4)
        c[0].download_button("⬇ Markdown report", render_markdown(sessions, sm, warns),
                             "report.md", "text/markdown")
        c[1].download_button("⬇ Text audit log", render_audit_text(sessions, sm, warns),
                             "audit_log.txt", "text/plain")
        c[2].download_button("⬇ Sessions CSV", render_sessions_csv(sessions), "sessions.csv", "text/csv")
        c[3].download_button("⬇ Subject summary CSV", render_subject_csv(sessions),
                             "subject_summary.csv", "text/csv")
        if st.button("Also write all reports to the exports/ folder"):
            paths = export_all(sessions, ARGS.exports, TODAY, cfg)
            st.success("Wrote: " + ", ".join(p.name for p in paths))
        with tempfile.TemporaryDirectory() as tmp:
            png = save_chart(sessions, Path(tmp) / "chart.png")
            if png:
                st.image(png.read_bytes(), caption="Matplotlib chart (also included in exports)")
            else:
                st.caption("Install matplotlib to render the static PNG chart.")

# ------------------------------------------------------------------- Import
elif page == "Import":
    st.subheader("Bulk import from CSV")
    st.caption("Required columns: `date`, `subject`, `focused_minutes`. "
               "Optional: `pomodoros`, `break_minutes`, `notes`. Every row is validated; "
               "bad rows are skipped and listed below.")
    up = st.file_uploader("Choose a CSV file", type=["csv"])
    c1, c2 = st.columns(2)
    sample = ROOT / "data" / "sample_sessions.csv"
    if sample.exists() and c1.button("Load the 40-row sample dataset"):
        res = import_csv_file(sample, storage, Path(ARGS.exports) / "import_errors.log", TODAY)
        st.success(res.summary_line())
    c2.download_button("⬇ Download CSV template",
                       "date,subject,focused_minutes,pomodoros,break_minutes,notes\n"
                       f"{TODAY.isoformat()},Mathematics,50,2,5,Example row\n", "template.csv", "text/csv")
    if up is not None:
        text = _decode(up.getvalue())
        try:
            st.caption("Preview (first 20 rows)")
            st.dataframe(pd.read_csv(io.StringIO(text), dtype=str, nrows=20, on_bad_lines="skip"),
                         hide_index=True)
        except Exception:                                   # preview is best-effort only
            st.caption("Preview unavailable - the importer will still validate every row.")
        if st.button("Import this file", type="primary"):
            res = import_csv_text(text, storage, TODAY)
            if res.fatal:
                st.error(res.summary_line())
            else:
                (st.warning if res.errors else st.success)(res.summary_line())
            if res.errors:
                err_df = pd.DataFrame(res.errors, columns=["Row", "Reason"])
                st.dataframe(err_df, hide_index=True)
                log = Path(ARGS.exports) / "import_errors.log"
                try:
                    write_error_log(res, up.name, log)
                except OSError:
                    pass
                st.download_button("⬇ Download error log",
                                   "\n".join(f"Row {r}: {m}" for r, m in res.errors),
                                   "import_errors.log", "text/plain")
