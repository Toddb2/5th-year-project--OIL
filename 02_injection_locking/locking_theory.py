"""Expected locking range against injection ratio, in GHz and in master current.

  python 02_injection_locking/locking_theory.py
  python 02_injection_locking/locking_theory.py --alpha 3 5 --length-mm 0.75 --measured data/.../summary.json

kappa is estimated from the slave cavity length, group index and facet reflectivity (none of
which are on the FPL852P spec sheet, so treat the absolute numbers as order-of-magnitude).
The useful output is the shape: the window grows as sqrt(injection ratio), and the conversion
to master current shows how finely the master has to be tuned.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from oil852.config import DATA_ROOT, load_config  # noqa: E402
from oil852.locking import coupling_coefficient, ghz_per_pm, locking_range_ghz  # noqa: E402
from oil852.runio import log_run  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alpha", type=float, nargs="+", default=[3.0, 5.0], help="linewidth enhancement factor(s)")
    p.add_argument("--length-mm", type=float, default=1.0, help="slave cavity length")
    p.add_argument("--group-index", type=float, default=3.6)
    p.add_argument("--facet-R", type=float, default=0.3)
    p.add_argument("--measured", nargs="*", default=[], help="summary.json files from locking_map.py (uses their VOA setting as -injection ratio)")
    p.add_argument("--tuning-pm-per-mA", type=float, default=None, help="measured master tuning (default: config)")
    p.add_argument("--out", default=None, help="output folder (default data/theory)")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    tune = a.tuning_pm_per_mA or float(cfg["injection"]["master_tuning_pm_per_mA"])
    ghz_per_mA = tune * ghz_per_pm()
    kappa = coupling_coefficient(a.length_mm, a.group_index, a.facet_R)
    rho = np.linspace(-40, -5, 200)

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    for alpha in a.alpha:
        lo, hi = locking_range_ghz(rho, kappa, alpha)
        ax.fill_between(rho, lo, hi, alpha=0.25, label=f"alpha = {alpha:g}")
        ax2.plot(rho, (hi - lo) / ghz_per_mA, label=f"alpha = {alpha:g}")
    ax.axhline(0, color="#555", lw=0.8)
    ax.set_xlabel("Injection ratio P_inj / P_slave (dB)")
    ax.set_ylabel("Master - slave detuning (GHz)")
    ax.set_title(f"Locking range (kappa = {kappa:.2e} /s)")
    ax.legend(fontsize=8)
    ax2.set_xlabel("Injection ratio (dB)")
    ax2.set_ylabel("Window width in master current (mA)")
    ax2.set_title(f"At {tune:g} pm/mA = {ghz_per_mA:.2f} GHz/mA")
    for f in a.measured:
        s = json.loads(open(f).read())
        meta = json.loads((_Path(f).parent / "meta.json").read_text())
        for w in s["window_widths_mA"]:
            ax2.plot(-meta["voa_dB"], w, "ko", ms=4)
    ax2.legend(fontsize=8)
    for axx in (ax, ax2):
        axx.grid(alpha=0.3)
    fig.tight_layout()
    out = _Path(a.out) if a.out else DATA_ROOT / "theory"
    out.mkdir(parents=True, exist_ok=True)
    log_run(out)
    fig.savefig(out / "locking_range.png", dpi=150)
    lo, hi = locking_range_ghz(-20, kappa, a.alpha[0])
    (out / "locking_theory.json").write_text(json.dumps({
        "kappa_per_s": kappa, "alpha": a.alpha, "tuning_pm_per_mA": tune,
        "window_at_-20dB_GHz": [float(lo), float(hi)], "window_at_-20dB_mA": float((hi - lo) / ghz_per_mA)}, indent=2))
    print(f"kappa = {kappa:.2e} /s. At -20 dB injection, alpha {a.alpha[0]:g}: {lo:.2f} to +{hi:.2f} GHz "
          f"= {(hi - lo) / ghz_per_mA:.1f} mA of master current.")
    print(f"Saved {out / 'locking_range.png'}")


if __name__ == "__main__":
    main()
