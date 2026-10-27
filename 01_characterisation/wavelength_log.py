"""Record peak wavelength against current (and temperature) read off the OSA, spectrometer or
wavemeter, then fit the tuning coefficients and flag mode hops.

Record (the script sets each current if the KLD101 is connected; you type the wavelength):
  python 01_characterisation/wavelength_log.py --temp 25 --currents 60:200:10 --file data/tuning_DBR852PN.csv
Repeat at other temperatures with the same --file to build up the temperature dependence.

Analyse only:
  python 01_characterisation/wavelength_log.py --analyse data/tuning_DBR852PN.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import PREFLIGHT, add_common_args, confirm

import pandas as pd

from oil852.analysis import tuning_coefficients
from oil852.bench import Limits, open_instruments, ramp_to, safe_shutdown
from oil852.config import laser_spec, load_config
from oil852.plotting import plot_tuning

FIELDS = ["laser", "temperature_C", "current_mA", "wavelength_nm", "smsr_dB", "note"]


def analyse(path: Path):
    df = pd.read_csv(path).dropna(subset=["wavelength_nm"])
    res = tuning_coefficients(df)
    plot_tuning(df, path.with_suffix(".png"))
    path.with_name(path.stem + "_results.json").write_text(json.dumps(res, indent=2))
    for T, k in res["per_current"].items():
        print(f"{T:g} C: {k * 1000:.2f} pm/mA")
    for I, k in res["per_temperature"].items():
        print(f"{I:g} mA: {k:.4f} nm/C")
    for h in res["mode_hops"]:
        print(f"Mode hop at {h['temperature_C']:g} C between {h['between_mA']} mA: {h['jump_nm']:.3f} nm")
    print(f"Plot: {path.with_suffix('.png')}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--analyse", type=Path, default=None, help="only analyse an existing CSV")
    if "--analyse" in sys.argv:
        a = p.parse_args()
        analyse(a.analyse)
        return
    add_common_args(p)
    p.add_argument("--currents", required=True, help='"start:stop:step" in mA')
    p.add_argument("--file", type=Path, required=True, help="CSV to append to")
    a = p.parse_args()

    cfg = load_config(a.config)
    spec = laser_spec(cfg, a.laser)
    s0, s1, ds = (float(x) for x in a.currents.split(":"))
    currents = [round(s0 + k * ds, 3) for k in range(int((s1 - s0) / ds) + 1)]
    manual = a.mode in ("manual", "manual-driver")
    if a.mode == "sim":
        driver, _ = open_instruments(cfg, "sim", sim_temperature_C=a.temp)
    elif manual:
        driver, _ = open_instruments(cfg, "manual")
    else:  # auto: only the KLD101 is needed here
        from oil852.instruments.kld101 import KLD101
        d = cfg["driver"]
        driver = KLD101(d["serial"], d["kinesis_path"], d["full_scale_mA"], d.get("voltage_counts_per_V", 1000.0))
    driver.connect()
    Limits.build(cfg, spec, max(currents), driver.hardware_limit_mA())
    if a.mode != "sim":
        print(PREFLIGHT + "  [ ] 20-30 dB attenuation in front of the OSA input.\n")
        if not confirm("Ready?", a.yes):
            sys.exit("Stopped before switching on.")

    new = not a.file.exists()
    a.file.parent.mkdir(parents=True, exist_ok=True)
    f = open(a.file, "a", newline="")
    w = csv.DictWriter(f, fieldnames=FIELDS)
    if new:
        w.writeheader()
    now = 0.0
    try:
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        for I in currents:
            if manual:
                driver.set_current_mA(I)
            else:
                ramp_to(driver, I, now)
            now = I
            if a.mode == "sim":
                lam = driver.laser.wavelength_nm(I)
                smsr = ""
            else:
                s = input(f"{I:6.1f} mA  peak wavelength in nm (Enter = skip): ").strip()
                if not s:
                    continue
                lam = float(s)
                smsr = input("        SMSR in dB (Enter = skip): ").strip()
            w.writerow({"laser": spec.name, "temperature_C": a.temp, "current_mA": I, "wavelength_nm": lam,
                        "smsr_dB": smsr, "note": ""})
            f.flush()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        off = safe_shutdown(driver, now, manual)
        f.close()
        driver.close()
    print(f"{'Laser off.' if off else 'CHECK THE DRIVER IS OFF.'} Saved to {a.file}")
    analyse(a.file)


if __name__ == "__main__":
    main()
