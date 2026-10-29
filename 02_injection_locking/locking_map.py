"""Map where the slave locks: step the master current with the slave fixed, and record
whether the slave is locked at each point (from the OSA).

At each master current you either point the script at an exported OSA trace (it works out
the peak and SMSR itself) or type in locked y/n and the SMSR read off the screen.

  python 02_injection_locking/locking_map.py --temp 25 --slave-mA 400 --voa-dB 20 --currents 80:200:1
  python 02_injection_locking/locking_map.py --temp 25 --slave-mA 400 --voa-dB 20 --currents 80:200:1 --mode sim

The master is driven by the KLD101 (auto) or set by hand (manual). The slave current and the
VOA setting are typed in and saved with the run. Repeat at several VOA settings to see the
locking range grow with injection ratio.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402

import numpy as np  # noqa: E402

from oil852.bench import Limits, open_instruments, ramp_to, safe_shutdown  # noqa: E402
from oil852.cli import PREFLIGHT, confirm  # noqa: E402
from oil852.config import laser_spec, load_config  # noqa: E402
from oil852.locking import ghz_per_pm, locked_windows  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402
from oil852.spectrum import analyse_spectrum, load_spectrum, looks_locked  # noqa: E402

FIELDS = ["master_mA", "locked", "smsr_dB", "peak_nm", "trace_file"]


def sim_locked(I, centre=140.0, width=6.0, voa_dB=20):
    """Synthetic: a window that grows with injection, repeating every slave mode (~50 mA apart)."""
    w = width * 10 ** ((20 - voa_dB) / 20)
    return any(abs(I - c) < w / 2 for c in (centre - 50, centre, centre + 50))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--temp", type=float, required=True, help="master TEC set point (deg C)")
    p.add_argument("--slave-mA", type=float, required=True, help="slave current (set on its own driver)")
    p.add_argument("--slave-temp", type=float, default=None, help="slave TEC set point (deg C)")
    p.add_argument("--voa-dB", type=float, required=True, help="VOA attenuation from the calibration")
    p.add_argument("--currents", required=True, help='master "start:stop:step" in mA')
    p.add_argument("--mode", choices=["auto", "manual", "sim"], default="auto")
    p.add_argument("--tuning-pm-per-mA", type=float, default=None, help="measured master tuning (default: config)")
    p.add_argument("--config", default=None)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()

    cfg = load_config(a.config)
    spec = laser_spec(cfg, "DBR852PN")
    s0, s1, ds = (float(x) for x in a.currents.split(":"))
    currents = [round(s0 + k * ds, 3) for k in range(int(round((s1 - s0) / ds)) + 1)]
    if a.mode == "auto":
        from oil852.instruments.kld101 import KLD101
        d = cfg["driver"]
        driver = KLD101(d["serial"], d["kinesis_path"], d["full_scale_mA"], d.get("voltage_counts_per_V", 1000.0))
    else:
        driver, _ = open_instruments(cfg, "sim" if a.mode == "sim" else "manual")
    manual = a.mode == "manual"
    driver.connect()
    Limits.build(cfg, spec, max(currents), driver.hardware_limit_mA())
    if a.mode != "sim":
        print(PREFLIGHT + "  [ ] Slave on its own driver at the stated current; VOA set; OSA on the output tap.\n")
        if not confirm("Ready to step the master?", a.yes):
            _sys.exit("Stopped.")

    run = new_run_dir("OIL", "locking_map", a.temp)
    write_meta(run, {"kind": "locking_map", "master_temp_C": a.temp, "slave_mA": a.slave_mA,
                     "slave_temp_C": a.slave_temp, "voa_dB": a.voa_dB, "currents_mA": currents, "mode": a.mode})
    log = CsvLog(run / "locking_map.csv", FIELDS)
    rows, now = [], 0.0
    try:
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        for I in currents:
            if manual:
                driver.set_current_mA(I)
            else:
                ramp_to(driver, I, now, step_mA=5.0)
            now = I
            if a.mode == "sim":
                locked, smsr, peak, f = sim_locked(I, voa_dB=a.voa_dB), None, None, ""
                smsr = 45.0 if locked else 5.0
            else:
                f = input(f"{I:6.1f} mA  OSA trace file (Enter to type the result instead): ").strip().strip('"')
                if f:
                    r = analyse_spectrum(*load_spectrum(f))
                    smsr, peak = r.smsr_dB, r.peak_nm
                    locked = looks_locked(r)
                    print(f"        peak {peak:.4f} nm, SMSR {smsr if smsr is None else round(smsr, 1)} dB -> "
                          f"{'locked' if locked else 'not locked'}")
                else:
                    locked = input("        locked? [y/n]: ").strip().lower().startswith("y")
                    s = input("        SMSR in dB (Enter = skip): ").strip()
                    smsr, peak = (float(s) if s else None), None
            row = {"master_mA": I, "locked": int(locked), "smsr_dB": smsr, "peak_nm": peak, "trace_file": f}
            log.write(row)
            rows.append(row)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        off = safe_shutdown(driver, now, manual)
        log.close()
        driver.close()
    print(f"{'Master off.' if off else 'CHECK THE MASTER DRIVER IS OFF.'} Data: {run}")

    if not rows:
        return
    I = np.array([r["master_mA"] for r in rows])
    L = np.array([r["locked"] for r in rows], bool)
    wins = locked_windows(I, L)
    tune = a.tuning_pm_per_mA or float(cfg["injection"]["master_tuning_pm_per_mA"])
    ghz_per_mA = tune * ghz_per_pm()
    # each locked point stands for one current step, so a window spans (end - start + step)
    widths = [b - a_ + ds for a_, b in wins]
    summary = {"windows_mA": wins, "window_widths_mA": widths, "step_mA": ds,
               "window_widths_GHz": [w * ghz_per_mA for w in widths],
               "master_tuning_pm_per_mA": tune}
    (run / "summary.json").write_text(json.dumps(summary, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 2.8))
    ax.fill_between(I, 0, L.astype(float), step="mid", alpha=0.4, color="#1f4e8c")
    ax.set_yticks([0, 1], ["free running", "locked"])
    ax.set_xlabel("Master current (mA)")
    ax.set_title(f"Locking map: slave {a.slave_mA:g} mA, VOA {a.voa_dB:g} dB")
    fig.tight_layout()
    fig.savefig(run / "locking_map.png", dpi=150)
    for (s, e), g in zip(wins, summary["window_widths_GHz"]):
        print(f"Locked {s:g}-{e:g} mA  (~{g:.1f} GHz of master detuning)")


if __name__ == "__main__":
    main()
