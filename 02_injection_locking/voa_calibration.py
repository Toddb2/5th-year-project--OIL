"""Calibrate the VOA in the master path: transmitted power against control voltage (0-5 V).

The master runs at a fixed current and the power meter sits after the VOA. The control voltage
comes from AWG CH3 in DC mode (High-Z), or a bench supply limited to 5 V; never the MDT693B
piezo controller.

  python 02_injection_locking/voa_calibration.py --master-mA 150                     # you set each voltage
  python 02_injection_locking/voa_calibration.py --master-mA 150 --voa awg --drive-master
  python 02_injection_locking/voa_calibration.py --master-mA 150 --mode sim
  python 02_injection_locking/voa_calibration.py --set 2.5 --voa awg                 # one voltage, to check with a meter

--voa awg      the script sets the voltage on the AWG (commands in config/bench.toml [voa])
--drive-master the script switches the master on through the KLD101 at --master-mA and off at the end
               (otherwise set the master current yourself before starting)

Output: CSV, plot, and lookup.json (the full curve plus voltages every 5 dB). The experiment
runner uses the curve to set each injection ratio.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from oil852.config import laser_spec, load_config  # noqa: E402
from oil852.instruments.voa import open_voa  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402


def sim_voa(v):
    """Typical MEMS/absorptive VOA response: ~0 dB at 0 V rising to ~40 dB at 5 V."""
    return 0.6 + 40 / (1 + np.exp(-(v - 2.6) / 0.45))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--master-mA", type=float, default=None, help="master current")
    p.add_argument("--vmax", type=float, default=5.0)
    p.add_argument("--step", type=float, default=0.1)
    p.add_argument("--mode", choices=["auto", "manual", "sim"], default="auto",
                   help="auto = read the PM100 over USB; manual = type the power; sim = practice")
    p.add_argument("--voa", choices=["manual", "awg", "sim"], default=None,
                   help="who sets the control voltage (default: [voa] control in bench.toml; sim in sim mode)")
    p.add_argument("--drive-master", action="store_true", help="switch the master on through the KLD101")
    p.add_argument("--settle", type=float, default=0.3, help="seconds after each voltage change")
    p.add_argument("--set", type=float, default=None, help="just set this voltage and exit")
    p.add_argument("--config", default=None)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()
    if a.vmax > 5.0:
        _sys.exit("The V800PA control input is 0-5 V. Refusing --vmax above 5 V.")

    cfg = load_config(a.config)
    control = a.voa or ("sim" if a.mode == "sim" else cfg.get("voa", {}).get("control", "manual"))
    voa = open_voa(cfg, control)
    if a.set is not None:
        voa.set_V(a.set)
        print(f"VOA control set to {a.set:.3f} V ({control}). Check it with a multimeter.")
        return
    if a.master_mA is None:
        p.error("--master-mA is needed for a calibration")

    volts = np.round(np.arange(0, a.vmax + a.step / 2, a.step), 3)
    meter = None
    if a.mode == "auto":
        from oil852.instruments.pm100 import PM100
        meter = PM100(cfg["power_meter"].get("resource", ""), 852.0, int(cfg["power_meter"].get("average_count", 50)))

    driver, now = None, 0.0
    if a.drive_master and a.mode == "auto":
        from oil852.bench import Limits, ramp_to
        from oil852.instruments.kld101 import KLD101
        d = cfg["driver"]
        driver = KLD101(d["serial"], d["kinesis_path"], d["full_scale_mA"], d.get("voltage_counts_per_V", 1000.0))
        driver.connect()
        Limits.build(cfg, laser_spec(cfg, "DBR852PN"), a.master_mA, driver.hardware_limit_mA())
        voa.set_V(float(volts[-1]))  # start at maximum attenuation
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        ramp_to(driver, a.master_mA, 0.0)
        now = a.master_mA
        time.sleep(1.0)
    elif a.mode != "sim":
        input(f"Set the master to {a.master_mA:g} mA (output on) and press Enter... ")

    run = new_run_dir("VOA", "calibration", None)
    write_meta(run, {"kind": "voa_calibration", "master_current_mA": a.master_mA, "mode": a.mode,
                     "voa_control": control, "meter": getattr(meter, "idn", a.mode)})
    log = CsvLog(run / "voa.csv", ["control_V", "power_mW"])
    p0 = 0.09 * (a.master_mA - 50)  # sim only: DBR852PN-like output in mW
    rows = []
    try:
        for v in volts:
            if a.mode == "sim":
                voa.set_V(float(v))
                P = p0 * 10 ** (-sim_voa(v) / 10)
            else:
                voa.set_V(float(v))
                time.sleep(a.settle)
                P = meter.power_W() * 1000 if meter else float(input("  power in mW: "))
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
        if driver is not None:
            from oil852.bench import safe_shutdown
            off = safe_shutdown(driver, now)
            driver.close()
            print("Master off." if off else "CHECK THE MASTER DRIVER IS OFF.")
        elif a.mode != "sim" and not a.drive_master:
            print("You can switch the master off now.")
        voa.close()

    if len(rows) < 3:
        _sys.exit("Too few points to calibrate.")
    V, P = np.array(rows).T
    att = 10 * np.log10(P.max() / np.clip(P, 1e-12, None))
    # monotonic lookup: attenuation (dB) -> voltage, using the running maximum to ignore noise
    att_mono = np.maximum.accumulate(att)
    lookup = {f"{d} dB": round(float(np.interp(d, att_mono, V)), 3) for d in range(0, int(att_mono.max()) + 1, 5)}
    (run / "lookup.json").write_text(json.dumps({
        "insertion_loss_note": "relative to the lowest-loss point",
        "max_attenuation_dB": float(att.max()),
        "power_at_min_loss_mW": float(P.max()),
        "voltage_for_attenuation": lookup,
        "curve": {"control_V": V.tolist(), "attenuation_dB": att.tolist()}}, indent=2))
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
