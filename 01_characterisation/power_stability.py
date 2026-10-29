"""Log output power at a fixed current over time (warm-up drift and stability).

  python 01_characterisation/power_stability.py --temp 25 --current 150 --minutes 20
"""

from __future__ import annotations

import argparse
import sys
import time

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import PREFLIGHT, add_common_args, confirm

import pandas as pd

from oil852.bench import Limits, open_instruments, ramp_to, safe_shutdown
from oil852.config import laser_spec, load_config
from oil852.plotting import plot_stability
from oil852.runio import CsvLog, new_run_dir, write_meta


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--current", type=float, required=True, help="drive current in mA")
    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--interval", type=float, default=1.0, help="seconds between readings")
    a = p.parse_args()
    if a.mode == "manual":
        sys.exit("Stability logging needs the power meter connected (use auto or manual-driver).")

    cfg = load_config(a.config)
    spec = laser_spec(cfg, a.laser)
    driver, meter = open_instruments(cfg, a.mode, sim_temperature_C=a.temp)
    manual = a.mode == "manual-driver"
    driver.connect()
    st = driver.status()
    if st.blocking_problems(cfg["driver"]["polarity"]):
        sys.exit("Cannot start: " + "; ".join(st.blocking_problems(cfg["driver"]["polarity"])))
    limits = Limits.build(cfg, spec, a.current, driver.hardware_limit_mA()).for_meter(cfg, meter)
    att = float(getattr(meter, "attenuation_dB", 0.0))
    exp_sensor = max(spec.slope_typ_W_per_A * (a.current - spec.threshold_typ_mA), 0) / 10 ** (att / 10)
    if exp_sensor > 0.9 * limits.sensor_max_W * 1000:
        sys.exit(f"About {exp_sensor:.1f} mW would reach a {limits.sensor_max_W * 1000:g} mW sensor. "
                 "Lower --current or add attenuation ([power_meter] attenuation_dB).")
    if a.mode != "sim":
        print(PREFLIGHT)
        if not confirm(f"Run {spec.name} at {a.current:g} mA for {a.minutes:g} min?", a.yes):
            sys.exit("Stopped before switching on.")

    run = new_run_dir(spec.name, "stability", a.temp)
    write_meta(run, {"laser": spec.name, "kind": "stability", "tec_setpoint_C": a.temp, "current_mA": a.current,
                     "minutes": a.minutes, "interval_s": a.interval, "meter": meter.idn, "sensor": meter.sensor,
                     "attenuation_dB": att})
    log = CsvLog(run / "stability.csv", ["elapsed_s", "power_mW", "current_mA"])
    now = 0.0
    reason = "completed"
    try:
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        if manual:
            driver.set_current_mA(a.current)
        else:
            ramp_to(driver, a.current, 0.0)
        now = a.current
        t0 = time.time()
        end = t0 + a.minutes * 60
        while time.time() < end:
            P = meter.power_W() * 1000
            I = a.current if manual else driver.read().current_mA
            log.write({"elapsed_s": round(time.time() - t0, 2), "power_mW": P, "current_mA": I})
            print(f"\r{(time.time() - t0) / 60:6.2f} min  {P:9.4f} mW", end="")
            time.sleep(a.interval if a.mode != "sim" else 0.005)
    except KeyboardInterrupt:
        reason = "stopped by user"
    finally:
        off = safe_shutdown(driver, now, manual)
        log.close()
        driver.close()
        meter.close()
    print(f"\n{'Laser off' if off else 'CHECK THE DRIVER IS OFF'} ({reason}). Data: {run}")
    df = pd.read_csv(run / "stability.csv")
    if len(df) > 2:
        plot_stability(df, run / "stability.png", f"{spec.name} {a.current:g} mA, {a.temp:g} °C")
        print(f"Mean {df.power_mW.mean():.4f} mW, std {df.power_mW.std() / df.power_mW.mean() * 100:.2f} %")


if __name__ == "__main__":
    main()
