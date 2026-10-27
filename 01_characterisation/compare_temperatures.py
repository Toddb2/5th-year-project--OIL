"""Combine L-I-V runs taken at different TEC temperatures: threshold vs temperature and T0.

  python 01_characterisation/compare_temperatures.py data/2026-10-27/DBR852PN_LIV_20C_* data/2026-10-27/DBR852PN_LIV_25C_* data/2026-10-27/DBR852PN_LIV_30C_*

Each folder's temperature is read from its meta.json.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import ROOT  # noqa: F401

from oil852.analysis import analyse_li, characteristic_temperature, load_li
from oil852.config import DATA_ROOT
from oil852.plotting import plot_temperature_series


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--out", default=None, help="output folder (default data/<today>/temperature_series_<time>)")
    a = p.parse_args()
    curves = []
    for r in map(Path, a.runs):
        meta = json.loads((r / "meta.json").read_text())
        df = load_li(r / "liv.csv")
        curves.append((float(meta["tec_setpoint_C"]), df, analyse_li(df)))
    t0 = characteristic_temperature([c[0] for c in curves], [c[2].threshold_fit_mA for c in curves])
    out = Path(a.out) if a.out else DATA_ROOT / datetime.now().strftime("%Y-%m-%d") / f"temperature_series_{datetime.now():%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    plot_temperature_series(curves, t0, out / "temperature_series.png")
    summary = {"T0_K": t0, "runs": [{"run": str(r), "temperature_C": T, "threshold_mA": res.threshold_fit_mA,
                                     "slope_W_per_A": res.slope_W_per_A, "max_power_mW": res.max_power_mW}
                                    for r, (T, _, res) in zip(a.runs, curves)]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    for row in summary["runs"]:
        print(f"{row['temperature_C']:5.1f} C: I_th {row['threshold_mA']:.1f} mA, slope {row['slope_W_per_A']:.3f} W/A")
    print(f"T0 = {t0:.0f} K" if t0 else "Need two or more temperatures for T0")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
