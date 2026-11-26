"""Central configuration and logging defaults."""
from __future__ import annotations
import logging
import os
from pathlib import Path


def configure_logging(log_file: str | None = None) -> None:
    level = os.getenv("POMODORO_LOG_LEVEL", "WARNING").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = "WARNING"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, level), handlers=handlers,
                       format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
