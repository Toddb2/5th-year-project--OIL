"""Tune the TTC001 loop gains: try gentler P/I/D settings one after another, measure how each
settles after a 1 C step, keep the best. Laser off throughout. About 2.5 minutes per setting.

  python 01_characterisation/tec_tune.py                     # current gains, then five gentler sets
  python 01_characterisation/tec_tune.py --sets 5,1,20 3,1,10 2,0.5,5
  python 01_characterisation/tec_tune.py --mode sim          # practice on a simulated loop

For each setting: hold 25 C, step to 26 C, record the next 2 minutes (4 readings a second):
settling time (to within 0.1 C and staying there), the swing over the last minute, and the
error from the target. The best setting is left on the TTC001 at the end and printed, so you can
copy it into Kinesis (Settings -> Advanced, on BOTH the Current and Startup tabs, then Save).
Kinesis otherwise puts its own startup gains back the next time it opens.

Saves tune_log.csv, tec_tune.png and summary.md in data/<date>/TTC001_tec_tune_<time>/.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from oil852.config import load_config  # noqa: E402
from oil852.instruments.tec import SimTEC, TECError, open_tec  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402

DEFAULT_SETS = [(8, 2, 30), (5, 1, 20), (3, 1, 10), (2, 1, 5), (1, 0.5, 0)]


class SimLoopTEC(SimTEC):
    """A small TEC with a sensor lag, run by a PID like the TTC001's, in simulated time.
    High gains make it ring; gentle gains settle."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.T = 21.3      # chip
        self.Ts = 21.3     # thermistor (lags the chip)
        self.amb = 21.3
        self.gains = (15.0, 4.0, 60.0)
        self.integ = 0.0
        self.prev_err = 0.0
        self.I = 0.0
        self.t_sim = 0.0
        self._enabled = False
        self.rng = np.random.default_rng(0)
        self.delay = [21.3] * 25          # 0.5 s of transport delay at 20 ms steps
        self.loop_dt = 0.1                # controller update interval
        self._next_update = 0.0

    def step(self, dt):
        n = max(1, int(dt / 0.02))
        h = dt / n
        for _ in range(n):
            self.delay.append(self.Ts)
            seen = self.delay.pop(0) + self.rng.normal(0, 0.003)
            if self._enabled and self.t_sim >= self._next_update:
                P, Ii, D = self.gains
                err = self._set - seen
                self.integ = max(-50, min(50, self.integ + err * self.loop_dt))
                deriv = (err - self.prev_err) / self.loop_dt
                self.prev_err = err
                self.I = max(-0.5, min(0.5, 0.03 * P * err + 0.004 * Ii * self.integ + 0.002 * D * deriv))
                self._next_update = self.t_sim + self.loop_dt
            elif not self._enabled:
                self.I = 0.0
            self.T += h * (8.0 * self.I - (self.T - self.amb) / 40.0)
            self.Ts += h * (self.T - self.Ts) / 0.4
            self.t_sim += h

    def read_C(self):
        return self.Ts

    def tec_current_A(self):
        return self.I

    def loop_gains(self):
        return self.gains

    def set_loop_gains(self, p, i, d):
        self.gains = (float(p), float(i), float(d))
        self.integ = 0.0

    def persist(self):
        return True


def wait(tec, seconds, dt, sim):
    if sim:
        tec.step(seconds)
    else:
        time.sleep(seconds)


def measure(tec, target, seconds, dt, sim, label, log, t0, abort_swing=6.0):
    rows = []
    n = int(seconds / dt)
    for k in range(n):
        wait(tec, dt, dt, sim)
        T = tec.read_C()
        I = tec.tec_current_A() * 1000
        t = (tec.t_sim if sim else time.time()) - t0
        rows.append((t, T, I))
        log.write({"t_s": round(t, 2), "gains": label, "setpoint_C": target, "temperature_C": round(T, 3),
                   "tec_mA": round(I)})
        if k % max(1, int(1 / dt)) == 0:
            print(f"\r  {label:>14}  {k * dt:5.0f}/{seconds:g} s   T {T:7.3f} C -> {target:g}   TEC {I:+5.0f} mA   ",
                  end="", flush=True)
        if T < tec.min_C - 3 or T > tec.max_C + 5:
            tec.disable()
            raise TECError(f"{T:.2f} C is outside the safe range; TEC disabled.")
        if k * dt > 30 and abs(T - target) > abort_swing:
            print("\n  swinging too far: next setting")
            break
    print()
    return np.array(rows)


def score(rows, target, tol=0.1):
    t, T = rows[:, 0] - rows[0, 0], rows[:, 1]
    err = T - target
    last = t >= t[-1] - 60
    swing = float(T[last].max() - T[last].min())
    off = float(abs(err[last].mean()))
    outside = np.where(np.abs(err) > tol)[0]
    settle = None
    if len(outside) == 0:
        settle = 0.0
    elif outside[-1] < len(t) - 1 and t[-1] - t[outside[-1] + 1] >= 20:
        settle = float(t[outside[-1] + 1])
    rms_I = float(np.sqrt(np.mean(rows[last, 2] ** 2)))
    return {"settle_s": settle, "swing_last_min_C": swing, "offset_C": off, "rms_tec_mA": rms_I,
            "settled": settle is not None and swing < 2 * tol}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["auto", "sim"], default="auto")
    p.add_argument("--sets", nargs="*", default=None, help='gain sets to try, each "P,I,D" (Kinesis units)')
    p.add_argument("--base-C", type=float, default=25.0)
    p.add_argument("--step-C", type=float, default=1.0)
    p.add_argument("--record-s", type=float, default=120.0, help="seconds recorded after each step")
    p.add_argument("--persist", action="store_true", help="also save the best gains in the TTC001's memory")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    sim = a.mode == "sim"
    t = cfg.get("tec", {})
    if sim:
        tec = SimLoopTEC(sensor=t.get("sensor", "TH20kOhm"), r25_kohm=float(t.get("r25_kohm", 10)),
                         beta_K=float(t.get("beta_K", 3950)), min_C=float(t.get("min_C", 15)),
                         max_C=float(t.get("max_C", 35)))
    else:
        tec = open_tec(cfg, "auto")
    tec.connect()
    dt = 0.25
    try:
        start = tec.loop_gains()
        raw = None if sim else tec.loop_gains_raw()
        print(f"Gains now: P {start[0]:g}, I {start[1]:g}, D {start[2]:g}" + (f"   (raw {raw})" if raw else "")
              + "\nCheck these match the Kinesis panel. If they don't, stop (Ctrl+C) and tell Claude.")
        sets = [tuple(float(x) for x in s.split(",")) for s in a.sets] if a.sets else DEFAULT_SETS
        sets = [tuple(start)] + [s for s in sets if tuple(s) != tuple(start)]

        run = new_run_dir("TTC001", "tec_tune", None)
        log = CsvLog(run / "tune_log.csv", ["t_s", "gains", "setpoint_C", "temperature_C", "tec_mA"])
        t0 = tec.t_sim if sim else time.time()
        tec.set_C(a.base_C)
        tec.enable()
        print(f"Settling at {a.base_C:g} C first (60 s)")
        wait(tec, 60, dt, sim)
        results, traces = [], {}
        target = a.base_C
        try:
            for k, (P, I, D) in enumerate(sets):
                label = f"P{P:g} I{I:g} D{D:g}"
                tec.set_loop_gains(P, I, D)
                target = a.base_C + a.step_C if k % 2 == 0 else a.base_C
                tec.set_C(target)
                print(f"[{k + 1}/{len(sets)}] {label}: step to {target:g} C")
                rows = measure(tec, target, a.record_s, dt, sim, label, log, t0)
                sc = score(rows, target)
                results.append({"P": P, "I": I, "D": D, "label": label, "target_C": target, **sc})
                traces[label] = rows
                print(f"  settle {('%.0f s' % sc['settle_s']) if sc['settle_s'] is not None else 'never'}, "
                      f"swing {sc['swing_last_min_C']:.3f} C, offset {sc['offset_C']:.3f} C")
        except KeyboardInterrupt:
            print("\nStopped early; using the settings tried so far.")
        finally:
            log.close()

        if not results:
            tec.set_loop_gains(*start)
            print("Nothing measured; gains put back.")
            return

        def rank(r):
            return (0, r["settle_s"], r["swing_last_min_C"]) if r["settled"] else \
                   (1, r["swing_last_min_C"] + r["offset_C"], 0)
        best = min(results, key=rank)
        tec.set_loop_gains(best["P"], best["I"], best["D"])
        tec.set_C(a.base_C)
        persisted = tec.persist() if a.persist else False

        lines = ["# TTC001 loop tuning", "", f"Step of {a.step_C:g} C around {a.base_C:g} C, "
                 f"{a.record_s:g} s recorded per setting. Laser off.", "",
                 "| Gains (P, I, D) | Settling time | Swing, last minute (C) | Offset (C) | RMS TEC current (mA) | |",
                 "|---|---|---|---|---|---|"]
        for r in results:
            st = f"{r['settle_s']:.0f} s" if r["settle_s"] is not None else "never"
            mark = "**best**" if r is best else ("settled" if r["settled"] else "")
            lines.append(f"| {r['P']:g}, {r['I']:g}, {r['D']:g} | {st} | {r['swing_last_min_C']:.3f} | "
                         f"{r['offset_C']:.3f} | {r['rms_tec_mA']:.0f} | {mark} |")
        verdict = ("settles" if best["settled"] else "still swings; heatsinking is the next thing to check")
        lines += ["", f"Best: P {best['P']:g}, I {best['I']:g}, D {best['D']:g} ({verdict}). Left on the TTC001"
                  + (" and saved in its memory." if persisted else "."),
                  "", "Put the same numbers into Kinesis (TTC001 Settings -> Advanced) on BOTH the Current and "
                  "Startup tabs and press Save, or Kinesis restores its own gains next time it opens."]
        (run / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_meta(run, {"kind": "tec_tune", "start_gains": start, "results": results, "best": best})
        (run / "results.json").write_text(json.dumps({"start_gains": start, "results": results, "best": best},
                                                     indent=2))

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        n = len(traces)
        cols = 2 if n > 1 else 1
        fig, axes = plt.subplots(math.ceil(n / cols), cols, figsize=(5 * cols, 2.6 * math.ceil(n / cols)),
                                 squeeze=False)
        for ax, (lab, rows), r in zip(axes.flat, traces.items(), results):
            ax.plot(rows[:, 0] - rows[0, 0], rows[:, 1], color="#1f4e8c", lw=1)
            ax.axhline(r["target_C"], color="#d1495b", ls="--", lw=0.8)
            ax.set_title(f"{lab}" + ("  (best)" if r is best else ""), fontsize=9)
            ax.set_xlabel("Time after step (s)")
            ax.set_ylabel("T (C)")
            ax.grid(alpha=0.3)
        for ax in list(axes.flat)[n:]:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(run / "tec_tune.png", dpi=150)
        print("\n" + "\n".join(lines) + f"\n\nSaved {run}")
    finally:
        tec.close()


if __name__ == "__main__":
    main()
