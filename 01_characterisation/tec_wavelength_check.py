"""Is the TEC swing real, or only in the thermistor reading? Uses the laser's own wavelength as a
second thermometer.

  python 01_characterisation/tec_wavelength_check.py                  # 150 mA, 25 C, 90 s
  python 01_characterisation/tec_wavelength_check.py --mode sim       # practice

The DBR852PN moves about 0.06 nm per degree (tuning_typ_nm_per_C in config/bench.toml), and the
CCS spectrometer finds its peak to a few pm, so a real 1 C swing shows as ~60 pm. The script holds
the laser at a fixed current with the TEC regulating at --temp, and logs the thermistor reading,
the TEC current and the peak wavelength together, as fast as the instruments allow (~5-10 per s).

Verdict:
  real swing        wavelength-implied swing ~ thermistor swing: the laser really is cycling.
                    Heatsink the mount and check the gains Kinesis shows are the ones in use.
  reading pickup    thermistor swing >> wavelength-implied swing: the TEC current is corrupting the
                    reading. Next: "If the reading is pickup" in docs/bench_notes.md.

Needs: KLD101, TTC001 and CCS on USB; Kinesis and ThorSpectra closed; fibre into the CCS through
an attenuator. Saves log.csv, check.png and summary.md in data/<date>/<laser>_tec_wavelength_<T>C_<time>/.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from oil852.bench import Limits, open_instruments, ramp_to, safe_shutdown  # noqa: E402
from oil852.cli import PREFLIGHT, confirm  # noqa: E402
from oil852.config import laser_spec, load_config  # noqa: E402
from oil852.instruments.ccs import CCSError, auto_scan, peak_centre  # noqa: E402
from oil852.instruments.tec import SimTEC, TECError, open_tec  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402


class _PickupSimTEC(SimTEC):
    """Practice bench: the laser really swings 0.6 C, but TEC-current pickup makes the reading
    swing about 3.5 C, like the bench on 3 Nov."""

    def __init__(self, laser, **kw):
        super().__init__(**kw)
        self.laser, self.t0 = laser, time.time()

    def _phase(self):
        return 2 * math.pi * (time.time() - self.t0) / 0.5

    def true_C(self):
        return self._set + 0.3 * math.sin(self._phase() - 0.8)

    def tec_current_A(self):
        return -0.49 if math.sin(self._phase()) > 0 else 0.49

    def read_C(self):
        self.laser.temperature_C = self.true_C()
        return self.true_C() - 3.5 * self.tec_current_A() + np.random.normal(0, 0.01)


def lagged_fit(t, T, lam, max_lag_s=3.0):
    """Best linear fit of wavelength against the thermistor reading, allowing the wavelength to lag
    (heat takes time to reach the chip). Returns slope nm/C, r, lag s."""
    best = (0.0, 0.0, 0.0)
    grid = np.linspace(t[0], t[-1], max(len(t), 50))
    Ti = np.interp(grid, t, T)
    li = np.interp(grid, t, lam)
    dt = grid[1] - grid[0]
    for k in range(0, int(max_lag_s / dt) + 1):
        a, b = Ti[: len(Ti) - k], li[k:]
        if len(a) < 10 or a.std() == 0 or b.std() == 0:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if abs(r) > abs(best[1]):
            best = (float(np.polyfit(a, b, 1)[0]), r, k * dt)
    return best


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--laser", default="DBR852PN")
    p.add_argument("--temp", type=float, default=25.0, help="TEC set point (C)")
    p.add_argument("--current", type=float, default=150.0, help="laser current (mA)")
    p.add_argument("--seconds", type=float, default=90.0)
    p.add_argument("--mode", choices=["auto", "sim"], default="auto")
    p.add_argument("--config", default=None)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()

    cfg = load_config(a.config)
    spec = laser_spec(cfg, a.laser)
    k_nm_per_C = float(spec.extra.get("tuning_typ_nm_per_C", 0.06)) if hasattr(spec, "extra") else 0.06
    sim = a.mode == "sim"
    if sim:
        driver, _ = open_instruments(cfg, "sim", sim_temperature_C=a.temp)
        tc = cfg.get("tec", {})
        tec = _PickupSimTEC(driver.laser, min_C=float(tc.get("min_C", 15)), max_C=float(tc.get("max_C", 35)))
        from oil852.instruments.ccs import SimCCS
        ccs = SimCCS(driver.laser, driver)
        a.seconds = min(a.seconds, 6.0)
    else:
        from oil852.instruments.ccs import CCS
        from oil852.instruments.kld101 import KLD101
        d = cfg["driver"]
        driver = KLD101(d["serial"], d["kinesis_path"], d["full_scale_mA"], d.get("voltage_counts_per_V", 1000.0))
        tec = open_tec(cfg, "auto")
        sc = cfg.get("spectrometer", {})
        ccs = None
    driver.connect()
    try:
        tec.connect()
    except Exception:
        driver.close()
        raise
    try:
        if ccs is None:
            ccs = CCS(sc.get("resource", ""), sc.get("serial", ""), float(sc.get("integration_s", 1e-3)))
    except Exception:
        driver.close()
        tec.close()
        raise
    st = driver.status()
    problems = st.blocking_problems(cfg["driver"]["polarity"])
    if not sim and not st.psu_ok:
        problems.append("KLD101 power-supply bit is off: is its 15 V supply plugged in?")
    if problems:
        driver.close(), tec.close(), ccs.close()
        sys.exit("Cannot start: " + "; ".join(problems))
    Limits.build(cfg, spec, a.current, driver.hardware_limit_mA())
    if not sim:
        print(PREFLIGHT + "  [ ] Fibre into the CCS SMA input through an attenuator. ThorSpectra closed.\n")
        if not confirm(f"Run {spec.name} at {a.current:g} mA, TEC at {a.temp:g} C, for {a.seconds:g} s?", a.yes):
            driver.close(), tec.close(), ccs.close()
            sys.exit("Stopped before switching on.")

    run = new_run_dir(spec.name, "tec_wavelength", a.temp)
    log = CsvLog(run / "log.csv", ["t_s", "thermistor_C", "tec_mA", "wavelength_nm", "peak"])
    rows, now, ended = [], 0.0, "completed"
    try:
        tec.set_C(a.temp)
        tec.enable()
        driver.set_constant_current()
        driver.set_current_mA(0.0)
        driver.enable()
        ramp_to(driver, a.current, 0.0)
        now = a.current
        print("Setting the spectrometer exposure...")
        auto_scan(ccs, n_avg=1)  # sets the integration time once; fixed for the run
        if not sim:
            print("Letting the laser warm up for 20 s...")
            time.sleep(20)
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            T = tec.read_C()
            I = tec.tec_current_A() * 1000
            y = ccs.scan()
            lam, _, top = peak_centre(ccs.wavelengths, y)
            row = {"t_s": round(time.time() - t0, 3), "thermistor_C": round(T, 3), "tec_mA": round(I),
                   "wavelength_nm": round(lam, 5), "peak": round(top, 3)}
            log.write(row)
            rows.append(row)
            print(f"\r  {row['t_s']:6.1f} s   thermistor {T:7.3f} C   TEC {I:+5.0f} mA   {lam:.4f} nm   ",
                  end="", flush=True)
            if top > 0.98:
                print("\n  (spectrum saturating: add attenuation)")
            if sim:
                time.sleep(0.01)
        print()
    except KeyboardInterrupt:
        ended = "stopped by user"
    except (TECError, CCSError) as exc:
        ended = f"error: {exc}"
        print(f"\n{exc}")
    finally:
        off = safe_shutdown(driver, now, False)
        log.close()
        driver.close()
        ccs.close()
        tec.close()  # TEC left regulating at the set point
    print(f"{'Laser off.' if off else 'CHECK THE DRIVER IS OFF.'} ({ended})")
    if len(rows) < 20:
        sys.exit(f"Only {len(rows)} readings: not enough to judge. Data: {run}")

    t = np.array([r["t_s"] for r in rows], float)
    T = np.array([r["thermistor_C"] for r in rows], float)
    I = np.array([r["tec_mA"] for r in rows], float)
    lam = np.array([r["wavelength_nm"] for r in rows], float)
    lam_d = lam - np.polyval(np.polyfit(t, lam, 1), t)  # remove slow drift
    T_d = T - np.polyval(np.polyfit(t, T, 1), t)
    p2p = lambda x: float(np.percentile(x, 98) - np.percentile(x, 2))  # noqa: E731
    therm_swing = p2p(T_d)
    lam_swing_pm = p2p(lam_d) * 1000
    real_swing = lam_swing_pm / 1000 / k_nm_per_C
    slope, r, lag = lagged_fit(t, T, lam)
    ratio = real_swing / therm_swing if therm_swing > 0 else float("nan")
    scatter_pm = float(np.std(np.diff(lam_d)) / math.sqrt(2) * 1000)

    if therm_swing < 0.2:
        verdict = (f"NO SWING: thermistor steady ({therm_swing:.2f} C). The TEC is holding today; "
                   "run tec_diagnostic.py and, if it settles, stage 1.")
    elif ratio >= 0.6:
        verdict = (f"REAL SWING: the wavelength says the laser moves ~{real_swing:.2f} C, close to the thermistor's "
                   f"{therm_swing:.2f} C. The reading is honest; the loop really is cycling. Heatsink the mount "
                   "(metal plate + thermal paste) and confirm in Kinesis which gains are actually in use.")
    elif ratio <= 0.35:
        verdict = (f"READING PICKUP: the thermistor swings {therm_swing:.2f} C but the laser only ~{real_swing:.2f} C "
                   f"({ratio * 100:.0f} %). TEC current is corrupting the reading, not a cabling short (pins open). "
                   "Next: 'If the reading is pickup' in docs/bench_notes.md.")
    else:
        verdict = (f"MIXED: thermistor {therm_swing:.2f} C, laser ~{real_swing:.2f} C ({ratio * 100:.0f} %). Part real, "
                   "part reading error.")

    summary = {"ended": ended, "current_mA": a.current, "setpoint_C": a.temp, "seconds": float(t[-1]),
               "readings": len(rows), "rate_per_s": len(rows) / float(t[-1]),
               "thermistor_swing_C": therm_swing, "wavelength_swing_pm": lam_swing_pm,
               "assumed_nm_per_C": k_nm_per_C, "laser_swing_C": real_swing, "ratio": ratio,
               "fit_nm_per_C": slope, "fit_r": r, "fit_lag_s": lag, "wavelength_noise_pm": scatter_pm,
               "mean_wavelength_nm": float(lam.mean()), "tec_current_range_mA": [float(I.min()), float(I.max())],
               "verdict": verdict}
    write_meta(run, {"kind": "tec_wavelength_check", **summary})
    (run / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = ["# TEC check against the laser wavelength", "",
             "| Quantity | Value |", "|---|---|",
             f"| Laser current, TEC set point | {a.current:g} mA, {a.temp:g} C |",
             f"| Readings | {len(rows)} in {t[-1]:.0f} s ({len(rows) / t[-1]:.1f} per s) |",
             f"| Thermistor swing (2-98 %) | {therm_swing:.2f} C |",
             f"| Wavelength swing (2-98 %) | {lam_swing_pm:.0f} pm |",
             f"| Wavelength noise per reading | {scatter_pm:.1f} pm |",
             f"| Laser swing implied ({k_nm_per_C:g} nm/C) | {real_swing:.2f} C |",
             f"| Ratio laser / thermistor | {ratio * 100:.0f} % |",
             f"| Wavelength vs thermistor fit | {slope * 1000:.1f} pm/C, r = {r:.2f}, lag {lag:.2f} s |",
             f"| TEC current range | {I.min():+.0f} to {I.max():+.0f} mA |",
             "", f"**Verdict:** {verdict}", ""]
    (run / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    axs[0].plot(t, T, color="#1f4e8c", lw=1)
    axs[0].set_ylabel("Thermistor (C)")
    axs[1].plot(t, I, color="#2a9d8f", lw=1)
    axs[1].axhline(0, color="#555", lw=0.8)
    axs[1].set_ylabel("TEC current (mA)")
    axs[2].plot(t, lam_d * 1000, color="#d1495b", lw=1)
    axs[2].set_ylabel("Wavelength − trend (pm)")
    sec = axs[2].secondary_yaxis("right", functions=(lambda x: x / 1000 / k_nm_per_C, lambda c: c * k_nm_per_C * 1000))
    sec.set_ylabel("Implied laser ΔT (C)")
    axs[2].set_xlabel("Time (s)")
    for ax in axs:
        ax.grid(alpha=0.3)
    axs[0].set_title(f"{spec.name} {a.current:g} mA, TEC {a.temp:g} C: thermistor vs wavelength")
    fig.tight_layout()
    fig.savefig(run / "check.png", dpi=150)
    print(f"Saved {run}")


if __name__ == "__main__":
    main()
