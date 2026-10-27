"""Calibrate the VOA in the master path: transmitted power against control voltage (0-5 V).

The master runs at a fixed current (set it on the KLD101 first). You step the VOA control
voltage (AWG CH3 in DC mode with High-Z load, or a bench supply limited to 5 V; never the
MDT693B piezo controller) and the script reads the power meter after the VOA.

  python 02_injection_locking/voa_calibration.py --master-mA 150 --vmax 5 --step 0.1
  python 02_injection_locking/voa_calibration.py --master-mA 150 --mode sim

Output: CSV, plot, and a lookup of the control voltage for each attenuation in dB, which is
what you'll use to set the injection ratio.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402

import numpy as np  # noqa: E402

from oil852.config import load_config  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402


def sim_voa(v):
    """Typical MEMS/absorptive VOA response: ~0 dB at 0 V rising to ~40 dB at 5 V."""
    return 0.6 + 40 / (1 + np.exp(-(v - 2.6) / 0.45))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--master-mA", type=float, required=True, help="master current you set on the KLD101")
    p.add_argument("--vmax", type=float, default=5.0)
    p.add_argument("--step", type=float, default=0.1)
    p.add_argument("--mode", choices=["auto", "manual", "sim"], default="auto",
                   help="auto = read the PM100 over USB; manual = type the power; sim = practice")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    if a.vmax > 5.0:
        _sys.exit("The V800PA control input is 0-5 V. Refusing --vmax above 5 V.")

    cfg = load_config(a.config)
    volts = np.round(np.arange(0, a.vmax + a.step / 2, a.step), 3)
    meter = None
    if a.mode == "auto":
        from oil852.instruments.pm100 import PM100
        meter = PM100(cfg["power_meter"].get("resource", ""), 852.0, int(cfg["power_meter"].get("average_count", 50)))
    run = new_run_dir("VOA", "calibration", None)
    write_meta(run, {"kind": "voa_calibration", "master_current_mA": a.master_mA, "mode": a.mode,
                     "meter": getattr(meter, "idn", a.mode)})
    log = CsvLog(run / "voa.csv", ["control_V", "power_mW"])
    p0 = 0.09 * (a.master_mA - 50)  # sim only: DBR852PN-like output in mW
    rows = []
    try:
        for v in volts:
            if a.mode == "sim":
                P = p0 * 10 ** (-sim_voa(v) / 10)
            else:
                input(f"Set the VOA control to {v:.2f} V and press Enter... ")
                if meter:
                    P = meter.power_W() * 1000
                else:
                    P = float(input("  power in mW: "))
            log.write({"control_V": v, "power_mW": P})
            rows.append((v, P))
            if a.mode != "sim":
                print(f"  {v:5.2f} V  {P:10.5f} mW")
    except KeyboardInterrupt:
        print("\nStopped early; data so far is saved.")
    finally:
        log.close()
        if meter:
            meter.close()

    V, P = np.array(rows).T
    att = 10 * np.log10(P.max() / np.clip(P, 1e-12, None))
    # monotonic lookup: attenuation (dB) -> voltage, using the running maximum to ignore noise
    att_mono = np.maximum.accumulate(att)
    lookup = {f"{d} dB": round(float(np.interp(d, att_mono, V)), 3) for d in range(0, int(att_mono.max()) + 1, 5)}
    (run / "lookup.json").write_text(json.dumps({"insertion_loss_note": "relative to the lowest-loss point",
                                                 "voltage_for_attenuation": lookup}, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(V, att, "o-", ms=3)
    ax.set_xlabel("VOA control voltage (V)")
    ax.set_ylabel("Attenuation relative to minimum (dB)")
    ax.set_title(f"VOA calibration, master at {a.master_mA:g} mA")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(run / "voa.png", dpi=150)
    print(f"Max attenuation {att.max():.1f} dB. Lookup: {lookup}\nSaved {run}")


if __name__ == "__main__":
    main()
