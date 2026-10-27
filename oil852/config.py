"""Load bench settings from config/bench.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "bench.toml"
DATA_ROOT = REPO_ROOT / "data"


@dataclass
class LaserSpec:
    name: str
    role: str
    max_current_mA: float
    threshold_typ_mA: float
    slope_typ_W_per_A: float
    tec_current_limit_A: float
    extra: dict


def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, "rb") as f:
        return tomllib.load(f)


def laser_spec(cfg: dict, name: str) -> LaserSpec:
    lasers = cfg.get("lasers", {})
    if name not in lasers:
        known = ", ".join(lasers) or "none"
        raise KeyError(f"Laser '{name}' is not in config/bench.toml (known: {known})")
    d = dict(lasers[name])
    return LaserSpec(
        name=name,
        role=d.pop("role", ""),
        max_current_mA=float(d.pop("max_current_mA")),
        threshold_typ_mA=float(d.pop("threshold_typ_mA", 0.0)),
        slope_typ_W_per_A=float(d.pop("slope_typ_W_per_A", 0.0)),
        tec_current_limit_A=float(d.pop("tec_current_limit_A", 0.0)),
        extra=d,
    )
