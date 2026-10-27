"""Re-analyse saved L-I-V runs (e.g. after editing the analysis, or for a CSV typed up by hand).

  python 01_characterisation/analyse_li.py data/2026-10-27/DBR852PN_LIV_25C_143012
  python 01_characterisation/analyse_li.py my_readings.csv --title "DBR852PN, 25 C, by hand"

A hand-typed CSV needs columns current_mA and power_mW (voltage_V and pd_mA optional).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import ROOT  # noqa: F401

from oil852.analysis import analyse_li, load_li
from oil852.plotting import plot_liv


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="+", help="run folders or CSV files")
    p.add_argument("--title", default=None)
    a = p.parse_args()
    for path in map(Path, a.paths):
        csv = path / "liv.csv" if path.is_dir() else path
        out = csv.parent
        df = load_li(csv)
        res = analyse_li(df)
        stem = "" if path.is_dir() else csv.stem + "_"
        (out / f"{stem}results.json").write_text(json.dumps(res.as_dict(), indent=2))
        plot_liv(df, res, a.title or out.name, out / f"{stem}liv.png")
        print(f"{out.name}: I_th {res.threshold_fit_mA:.1f} mA (fit) / {res.threshold_d2_mA:.1f} mA (kink), "
              f"slope {res.slope_W_per_A:.3f} W/A, max {res.max_power_mW:.2f} mW, "
              f"Rs {res.series_resistance_ohm if res.series_resistance_ohm is None else round(res.series_resistance_ohm, 2)} ohm")


if __name__ == "__main__":
    main()
