"""Analyse OSA (or CCS spectrometer) exports: peak wavelength, SMSR, FP mode spacing, locked or not.

  python 02_injection_locking/osa_spectrum.py trace1.csv trace2.csv
  python 02_injection_locking/osa_spectrum.py traces/*.csv --master-nm 852.112
  python 02_injection_locking/osa_spectrum.py --demo        # synthetic free-running and locked traces

Each trace needs two columns (wavelength, power); header lines are skipped. Power in dBm is
detected automatically; pass --unit mW or W for linear exports.
Note: the CCS spectrometer (~0.5 nm resolution) cannot resolve the FP modes (~0.1 nm apart)
or measure SMSR; use the OSA for locking work.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from oil852.config import DATA_ROOT  # noqa: E402
from oil852.spectrum import analyse_spectrum, load_spectrum, looks_locked, synthetic_fp, to_csv_text  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("traces", nargs="*", type=Path)
    p.add_argument("--unit", default="auto", choices=["auto", "dBm", "mW", "W"])
    p.add_argument("--master-nm", type=float, default=None, help="master wavelength, for the locked test")
    p.add_argument("--smsr-min", type=float, default=30.0, help="SMSR (dB) needed to call it locked")
    p.add_argument("--demo", action="store_true")
    a = p.parse_args()

    if a.demo:
        demo = DATA_ROOT / "demo_spectra"
        demo.mkdir(parents=True, exist_ok=True)
        for name, locked in (("free_running", False), ("locked", True)):
            wl, pw = synthetic_fp(locked, master_nm=852.0)
            (demo / f"{name}.csv").write_text(to_csv_text(wl, pw))
        a.traces = sorted(demo.glob("*.csv"))
        a.master_nm = 852.0
    if not a.traces:
        p.error("give one or more trace files, or --demo")

    results = {}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for path in a.traces:
        wl, pw = load_spectrum(path, a.unit)
        r = analyse_spectrum(wl, pw)
        locked = looks_locked(r, a.master_nm, a.smsr_min)
        results[path.name] = {**r.as_dict(), "looks_locked": locked}
        ax.plot(wl, pw, lw=0.9, label=f"{path.stem} ({'locked' if locked else 'not locked'})")
        smsr = f"{r.smsr_dB:.1f} dB" if r.smsr_dB is not None else "n/a"
        spacing = f"{r.mode_spacing_nm * 1000:.0f} pm" if r.mode_spacing_nm else "n/a"
        print(f"{path.name}: peak {r.peak_nm:.4f} nm at {r.peak_dBm:.1f} dBm, SMSR {smsr}, "
              f"{r.n_modes_within_20dB} modes within 20 dB, spacing {spacing}, "
              f"{'LOCKED' if locked else 'not locked'}")
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Power (dBm)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = a.traces[0].parent
    fig.savefig(out / "spectra.png", dpi=150)
    (out / "spectra_results.json").write_text(json.dumps(results, indent=2))
    print(f"Plot and results saved in {out}")


if __name__ == "__main__":
    main()
