"""Run folders: every measurement gets data/<date>/<laser>_<kind>_<temp>C_<time>/ with a CSV,
a metadata JSON and plots."""

from __future__ import annotations

import csv
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from .config import DATA_ROOT, REPO_ROOT


def new_run_dir(laser: str, kind: str, temperature_C: float | None, root: Path | None = None) -> Path:
    now = datetime.now()
    t = f"_{temperature_C:g}C" if temperature_C is not None else ""
    d = (root or DATA_ROOT) / now.strftime("%Y-%m-%d") / f"{laser}_{kind}{t}_{now.strftime('%H%M%S')}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip() or "none"
    except Exception:
        return "none"


def write_meta(run_dir: Path, meta: dict):
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "host": platform.node(),
            "code_version": git_commit(), **meta}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))


class CsvLog:
    """Writes each row straight to disk, so an interrupted run keeps its data."""

    def __init__(self, path: Path, fields: list[str]):
        self.path = path
        self.fields = fields
        self._f = open(path, "w", newline="")
        self._w = csv.DictWriter(self._f, fieldnames=fields)
        self._w.writeheader()
        self._f.flush()

    def write(self, row: dict):
        self._w.writerow({k: row.get(k, "") for k in self.fields})
        self._f.flush()

    def close(self):
        self._f.close()
