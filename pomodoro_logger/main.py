#!/usr/bin/env python3
"""Pomodoro Study Session Logger - entry point.

    python main.py              terminal interface (no dependencies)
    python main.py --gui        modern Streamlit web interface
    python main.py --seed       replace data with the 40-session sample set first
    python main.py --data FILE  use a different JSON data file
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pomodoro.config import configure_logging  # noqa: E402
from pomodoro.storage import Storage          # noqa: E402
from pomodoro.ui_cli import CLI               # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):          # box-drawing / emoji safe on any console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Pomodoro Study Session Logger")
    ap.add_argument("--data", default=str(ROOT / "data" / "sessions.json"), help="JSON data file")
    ap.add_argument("--exports", default=str(ROOT / "exports"), help="folder for generated reports")
    ap.add_argument("--gui", action="store_true", help="launch the Streamlit GUI instead")
    ap.add_argument("--seed", action="store_true", help="load the sample dataset into the data file")
    args = ap.parse_args(argv)
    configure_logging(str(Path(args.exports) / "app.log"))

    if args.seed:
        sample = ROOT / "data" / "sample_sessions.json"
        if not sample.exists():
            print("Sample data missing - run: python generate_sample_data.py", file=sys.stderr)
            return 1
        Path(args.data).parent.mkdir(parents=True, exist_ok=True)
        Path(args.data).write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Seeded {args.data} from {sample.name}.")

    if args.gui:
        try:
            import streamlit  # noqa: F401
        except ImportError:
            print("Streamlit is not installed. Run:  pip install streamlit pandas matplotlib",
                  file=sys.stderr)
            return 1
        env_cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app_gui.py"),
                   "--", "--data", args.data, "--exports", args.exports]
        return subprocess.call(env_cmd)

    return CLI(Storage(args.data), args.exports).run()


if __name__ == "__main__":
    raise SystemExit(main())
