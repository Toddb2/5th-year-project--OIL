"""Measure the L-I-V curve: optical power, forward voltage and monitor-photodiode current
against drive current, at one TEC temperature.

Examples
  python 01_characterisation/li_sweep.py --temp 25 --mode sim                 # practice run, no hardware
  python 01_characterisation/li_sweep.py --temp 25 --stop 200 --zero          # real run, zero the meter first
  python 01_characterisation/li_sweep.py --temp 25 --stop 200 --mode manual-driver   # if the KLD101 DLL won't connect

Default steps for the DBR852PN: 2 mA up to 90 mA (through the ~50 mA threshold), then 5 mA.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import PREFLIGHT, add_common_args, confirm

from oil852.analysis import analyse_li, load_li
from oil852.bench import Limits, open_instruments, ramp_to, safe_shutdown
from oil852.config import laser_spec, load_config
from oil852.plotting import plot_liv
from oil852.runio import CsvLog, new_run_dir, write_meta

FIELDS = ["set_mA", "current_mA", "power_mW", "power_std_mW", "voltage_V", "pd_mA", "elapsed_s"]


def build_currents(steps: str | None, stop: float, ith_typ: float) -> list[float]:
    if not steps:
        dense_to = min(stop, max(ith_typ * 1.8, 20.0))
        steps = f"0:{dense_to:g}:2,{dense_to:g}:{stop:g}:5"
    pts = []
    for seg in steps.split(","):
        a, b, s = (float(x) for x in seg.split(":"))
        x = a
        while x <= b + 1e-9:
            pts.append(round(x, 3))
            x += s
    pts = sorted(set(p for p in pts if p <= stop + 1e-9))
    if pts[-1] < stop:
        pts.append(stop)
    return pts


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--stop", type=float, default=200.0, help="highest current in mA (default 200)")
    p.add_argument("--steps", default=None, help='custom segments "start:stop:step,..." in mA')
    p.add_argument("--settle", type=float, default=0.5, help="seconds to wait after each step (default 0.5)")
    p.add_argument("--reads", type=int, default=3, help="power readings per point (default 3)")
    p.add_argument("--zero", action="store_true", help="zero the power meter first (laser must be off)")
    p.add_argument("--note", default="", help="free-text note saved with the run")
    a = p.parse_args()

    cfg = load_config(a.config)
    spec = laser_spec(cfg, a.laser)
    driver, meter = open_instruments(cfg, a.mode, sim_temperature_C=a.temp)
    manual = a.mode in ("manual", "manual-driver")
    driver.connect()

    st = driver.status()
    blocking = st.blocking_problems(cfg["driver"]["polarity"])
    if blocking:
        print("Cannot start:\n  - " + "\n  - ".join(blocking))
        driver.close()
        sys.exit(1)
    for w in st.warnings():
        print(f"  ! {w}")

    hw = driver.hardware_limit_mA()
    limits = Limits.build(cfg, spec, a.stop, hw).for_meter(cfg, meter)
    att = float(getattr(meter, "attenuation_dB", 0.0))
    currents = build_currents(a.steps, limits.max_current_mA, spec.threshold_typ_mA)
    expected_mW = max(spec.slope_typ_W_per_A * (limits.max_current_mA - spec.threshold_typ_mA), 0)
    print(f"\n{spec.name} at {a.temp:g} C: {len(currents)} points, 0 to {limits.max_current_mA:g} mA "
          f"(KLD101 limit {'~%.0f mA' % hw if hw else 'not read'}).")
    at_sensor = expected_mW / 10 ** (att / 10)
    print(f"Expected top power ~{expected_mW:.1f} mW ({at_sensor:.2f} mW at the sensor after {att:g} dB); "
          f"sensor limit {limits.sensor_max_W * 1000:g} mW. Meter: {meter.idn} / sensor {meter.sensor}")
    if at_sensor > 0.9 * limits.sensor_max_W * 1000:
        I_ok = spec.threshold_typ_mA + 0.85 * limits.sensor_max_W * 1000 * 10 ** (att / 10) / max(spec.slope_typ_W_per_A, 1e-6)
        print(f"  ! That is over the sensor limit. The sweep will stop itself near {I_ok:.0f} mA. For the full range put a "
              f"fibre attenuator in front of the sensor and set [power_meter] attenuation_dB.")
    if a.mode != "sim":
        print(PREFLIGHT)
        if not confirm("All checked and ready to switch the laser on?", a.yes):
            driver.close()
            sys.exit("Stopped before switching on.")

    if a.zero:
        meter.zero()

    run = new_run_dir(spec.name, "LIV", a.temp)
    log = CsvLog(run / "liv.csv", FIELDS)
    write_meta(run, {"laser": spec.name, "kind": "LIV", "tec_setpoint_C": a.temp, "mode": a.mode,
                     "stop_mA": limits.max_current_mA, "currents_mA": currents, "settle_s": a.settle,
                     "reads_per_point": a.reads, "meter": meter.idn, "sensor": meter.sensor,
                     "meter_wavelength_nm": meter.wavelength_nm, "driver_hw_limit_mA": hw,
                     "attenuation_dB": att, "sensor_limit_mW": limits.sensor_max_W * 1000,
                     "status_bits": st.raw_bits, "note": a.note})

    now_mA, t0, stop_reason = 0.0, time.time(), "completed"
    try:
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        print(f"\n{'set':>7} {'I meas':>8} {'P (mW)':>9} {'V (V)':>7} {'PD (mA)':>8}")
        for I in currents:
            if manual:
                driver.set_current_mA(I)
            else:
                ramp_to(driver, I, now_mA, step_mA=5.0)
            now_mA = I
            time.sleep(a.settle)
            rd = driver.read()
            powers = [meter.power_W() * 1000 for _ in range(1 if manual else a.reads)]
            P = statistics.fmean(powers)
            Pstd = statistics.pstdev(powers) if len(powers) > 1 else 0.0
            log.write({"set_mA": I, "current_mA": round(rd.current_mA, 3), "power_mW": P, "power_std_mW": Pstd,
                       "voltage_V": rd.voltage_V, "pd_mA": rd.pd_current_mA, "elapsed_s": round(time.time() - t0, 2)})
            v = f"{rd.voltage_V:.3f}" if rd.voltage_V is not None else "-"
            pd = f"{rd.pd_current_mA:.4f}" if rd.pd_current_mA is not None else "-"
            print(f"{I:7.1f} {rd.current_mA:8.2f} {P:9.4f} {v:>7} {pd:>8}")

            if getattr(meter, "last_raw_W", P / 1000) > 0.9 * limits.sensor_max_W:
                stop_reason = "power near sensor limit (add attenuation to go higher)"
                break
            if not manual and I >= 10 and rd.current_mA < 0.8 * I:
                stop_reason = (f"measured current {rd.current_mA:.1f} mA is well below the set point: "
                               "open circuit, wrong polarity or driver at its voltage limit")
                break
            if not manual and driver.status().current_limit_reached and I < limits.max_current_mA:
                stop_reason = "driver reports its current limit was reached"
                break
    except KeyboardInterrupt:
        stop_reason = "stopped by user (Ctrl+C)"
    except Exception as exc:
        stop_reason = f"error: {exc}"
    finally:
        off = safe_shutdown(driver, now_mA, manual)
        log.close()
        driver.close()
        meter.close()
    print(f"\n{'Laser off.' if off else 'CHECK THE DRIVER IS OFF.'} Run ended: {stop_reason}\nData: {run}")

    df = load_li(run / "liv.csv")
    try:
        res = analyse_li(df)
    except Exception as exc:
        print(f"Analysis skipped ({exc}).")
        return
    (run / "results.json").write_text(json.dumps({"stop_reason": stop_reason, **res.as_dict()}, indent=2))
    plot_liv(df, res, f"{spec.name} L–I–V at {a.temp:g} °C", run / "liv.png")
    print(f"Threshold: {res.threshold_fit_mA:.1f} mA (linear fit), {res.threshold_d2_mA:.1f} mA (kink); "
          f"spec ~{spec.threshold_typ_mA:g} mA")
    print(f"Slope efficiency: {res.slope_W_per_A:.3f} W/A (spec ~{spec.slope_typ_W_per_A:g}), fit R² {res.fit_r2:.4f}")
    print(f"Max power: {res.max_power_mW:.2f} mW at {res.current_at_max_mA:.0f} mA")
    if res.series_resistance_ohm is not None:
        print(f"Series resistance: {res.series_resistance_ohm:.2f} ohm, V intercept {res.turn_on_voltage_V:.2f} V")
    print(f"Plot: {run / 'liv.png'}")


if __name__ == "__main__":
    main()
