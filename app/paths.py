"""Centralized paths separating curated read-only corpus from mutable user runtime data."""
from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURATED_DATA_DIR = ROOT / "brain_data"
SOURCES_DIR = ROOT / "sources"
BOOKS_DIR = ROOT / "books"
WEB_DIR = ROOT / "web"


def default_runtime_data_dir() -> Path:
    return Path(os.environ.get("TCM_DATA_DIR") or (ROOT / "data")).resolve()
