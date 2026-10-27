"""Capture the fast photodiode (or AWG) traces from the Tek 4 Series scope and analyse the pulses:
period, width (FWHM), timing jitter, amplitude spread and extinction.

  python 03_pulsed/scope_capture.py --channel 1 --shots 20 --label "slave 300 mA bias, 1 V pulses"
  python 03_pulsed/scope_capture.py --mode sim

Set the trigger, timebase and vertical scale on the scope first (50 ohm input for the DET08CFC).
The DET08CFC is ~5 GHz, so pulses much shorter than ~100 ps will read as detector-limited.
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

from oil852.config import load_config  # noqa: E402
from oil852.instruments.tek_scope import TekScope, synthetic_pulses  # noqa: E402
from oil852.pulses import analyse_pulses  # noqa: E402
from oil852.runio import new_run_dir, write_meta  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channel", type=int, default=1)
    p.add_argument("--shots", type=int, default=10, help="single acquisitions to grab")
    p.add_argument("--label", default="")
    p.add_argument("--mode", choices=["auto", "sim"], default="auto")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    scope = None if a.mode == "sim" else TekScope(cfg["scope"].get("address", ""))
    run = new_run_dir("scope", "pulses", None)
    write_meta(run, {"kind": "scope_capture", "channel": a.channel, "shots": a.shots, "label": a.label,
                     "scope": scope.idn if scope else "simulated"})
    results = []
    try:
        for k in range(a.shots):
            if scope:
                scope.single()
                t, v = scope.waveform(a.channel)
            else:
                t, v = synthetic_pulses(seed=k)
            np.savez_compressed(run / f"shot_{k:03d}.npz", t=t, v=v)
            try:
                r = analyse_pulses(t, v)
                results.append(r.as_dict())
                print(f"shot {k}: {r.n_pulses} pulses, period {r.period_ns:.3f} ns, FWHM {r.fwhm_ps:.0f} ps, "
                      f"jitter {r.timing_jitter_ps:.1f} ps")
            except ValueError as exc:
                print(f"shot {k}: {exc}")
    finally:
        if scope:
            scope.run()
            scope.close()
    if not results:
        return
    keys = ["period_ns", "fwhm_ps", "timing_jitter_ps", "amplitude_V", "amplitude_cv_pct"]
    summary = {k: {"mean": float(np.mean([r[k] for r in results])), "std": float(np.std([r[k] for r in results]))}
               for k in keys}
    (run / "summary.json").write_text(json.dumps({"label": a.label, "summary": summary, "shots": results}, indent=2))
    first = np.load(run / "shot_000.npz")
    t, v = first["t"], first["v"]
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(t * 1e9, v * 1e3, lw=0.7)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Signal (mV)")
    s = summary
    ax.set_title(f"{a.label or 'pulse train'}: FWHM {s['fwhm_ps']['mean']:.0f} ps, "
                 f"jitter {s['timing_jitter_ps']['mean']:.1f} ps")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(run / "trace.png", dpi=150)
    print(f"Saved {run}")


if __name__ == "__main__":
    main()
