"""TEC diagnostic: does the TEC heat, does it cool, and does it settle? Logs every second.

  python 01_characterisation/tec_diagnostic.py                 # about 9 minutes
  python 01_characterisation/tec_diagnostic.py --short         # about 4 minutes
  python 01_characterisation/tec_diagnostic.py --mode sim      # practice

Four phases, each starting from wherever the last one ended:
  A  TEC off            ambient drift (what the laser does on its own)
  B  heat               set point 3 C above the start: the temperature should rise, current positive
  C  cool               set point 2 C below where B ended: the temperature should fall, current negative
  D  hold 25 C          does the loop settle, or swing? (peak-to-peak and period of any oscillation)

Saves tec_log.csv (time, phase, temperature, set point, TEC current), tec_diagnostic.png and
summary.md with a verdict per phase, in data/<date>/TTC001_tec_diagnostic_<time>/.
Laser off throughout. Ctrl+C stops it and leaves the TEC holding 25 C.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from oil852.config import load_config  # noqa: E402
from oil852.instruments.tec import TECError, open_tec  # noqa: E402
from oil852.runio import CsvLog, new_run_dir, write_meta  # noqa: E402


def _current(tec) -> float | None:
    try:
        return tec.tec_current_A() * 1000
    except Exception:
        return None


def run_phase(tec, name, seconds, setpoint, log, rows, t0, dt):
    if setpoint is None:
        tec.disable()
    else:
        tec.set_C(setpoint)
        tec.enable()
    end = time.time() + seconds
    while time.time() < end:
        T = tec.read_C()
        I = _current(tec)
        row = {"t_s": round(time.time() - t0, 1), "phase": name, "temperature_C": round(T, 3),
               "setpoint_C": "" if setpoint is None else round(setpoint, 2), "tec_mA": "" if I is None else round(I)}
        log.write(row)
        rows.append(row)
        sp = "off" if setpoint is None else f"{setpoint:5.2f} C"
        print(f"\r  {name:10s} {row['t_s']:6.0f} s   T {T:7.3f} C   set {sp:>8}   TEC "
              f"{'-' if I is None else f'{I:+5.0f} mA'}      ", end="", flush=True)
        if T < tec.min_C - 3 or T > tec.max_C + 5:
            tec.disable()
            raise TECError(f"{T:.2f} C is outside the safe range; TEC disabled.")
        time.sleep(dt)
    print()


def summarise(rows, phase):
    r = [x for x in rows if x["phase"] == phase]
    if len(r) < 3:
        return None
    t = np.array([x["t_s"] for x in r], float)
    T = np.array([x["temperature_C"] for x in r], float)
    I = np.array([x["tec_mA"] for x in r if x["tec_mA"] != ""], float)
    tail = T[t >= t[-1] - min(120, (t[-1] - t[0]) / 2)]
    # oscillation period from crossings of the tail's mean
    d = tail - tail.mean()
    cross = np.where(np.diff(np.sign(d)) != 0)[0]
    tt = t[t >= t[-1] - min(120, (t[-1] - t[0]) / 2)]
    period = float(2 * np.mean(np.diff(tt[cross]))) if len(cross) >= 3 else None
    return {"seconds": float(t[-1] - t[0]), "T_start": float(T[0]), "T_end": float(T[-1]),
            "dT": float(T[-1] - T[0]), "rate_C_per_min": float(np.polyfit(t, T, 1)[0] * 60),
            "I_mean_mA": float(I.mean()) if I.size else None, "I_peak_mA": float(np.abs(I).max()) if I.size else None,
            "tail_p2p_C": float(tail.max() - tail.min()), "period_s": period}


def verdicts(s, setpoints):
    out = {}
    a = s.get("A")
    if a:
        out["A"] = f"ambient drift {a['rate_C_per_min']:+.2f} C/min with the TEC off"
    b = s.get("B")
    if b:
        if b["dT"] > 0.5:
            out["B"] = "HEATING WORKS: temperature rose with positive current"
        elif b["dT"] < -0.3 and (b["I_mean_mA"] or 0) > 50:
            out["B"] = "REVERSED: positive (heating) current made it colder. Swap TEC+ and TEC-."
        else:
            out["B"] = "little change: check the TEC current reads near the limit; TEC path may be open"
    c = s.get("C")
    if c:
        if c["dT"] < -0.5:
            out["C"] = "COOLING WORKS: temperature fell with negative current"
        elif c["dT"] > 0.3 and (c["I_mean_mA"] or 0) < -50:
            if b and b["dT"] > 0.5:
                out["C"] = ("COOLING MAKES IT HOTTER while heating works: the TEC can't dump heat. "
                            "The laser base needs a heatsink (metal plate + thermal paste).")
            else:
                out["C"] = "REVERSED: cooling current made it hotter. Swap TEC+ and TEC-."
        else:
            out["C"] = "weak cooling: poor heatsinking or current limit too low"
    d = s.get("D")
    if d:
        err = abs(d["T_end"] - setpoints["D"])
        if d["tail_p2p_C"] < 0.1 and err < 0.1:
            out["D"] = f"SETTLED at {setpoints['D']:g} C (last-2-min spread {d['tail_p2p_C']:.3f} C)"
        elif d["tail_p2p_C"] >= 0.3 and d["period_s"]:
            out["D"] = (f"OSCILLATING: {d['tail_p2p_C']:.2f} C peak-to-peak, period ~{d['period_s']:.0f} s. "
                        "Lower the proportional and integral gains (and heatsink the laser).")
        else:
            out["D"] = f"not settled yet: {err:.2f} C from target, spread {d['tail_p2p_C']:.2f} C"
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["auto", "sim"], default="auto")
    p.add_argument("--short", action="store_true", help="shorter phases (about 4 minutes)")
    p.add_argument("--hold-C", type=float, default=25.0)
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    tec = open_tec(cfg, a.mode)
    if a.mode == "sim":
        tec.tau_s = 20.0
    tec.connect()
    dur = {"A": 60, "B": 120, "C": 150, "D": 240} if not a.short else {"A": 30, "B": 60, "C": 60, "D": 90}
    dt = 1.0
    if a.mode == "sim":
        dur, dt = {k: v / 20 for k, v in dur.items()}, 0.05

    run = new_run_dir("TTC001", "tec_diagnostic", None)
    log = CsvLog(run / "tec_log.csv", ["t_s", "phase", "temperature_C", "setpoint_C", "tec_mA"])
    rows, setpoints = [], {}
    t0 = time.time()
    print(f"TEC diagnostic, about {sum(dur.values()) / 60:.0f} min. Laser stays off. Ctrl+C to stop.")
    try:
        print("A: TEC off (ambient drift)")
        setpoints["A"] = None
        run_phase(tec, "A", dur["A"], None, log, rows, t0, dt)
        T = tec.read_C()
        setpoints["B"] = min(T + 3.0, tec.max_C)
        print(f"B: heat, set point {setpoints['B']:.2f} C")
        run_phase(tec, "B", dur["B"], setpoints["B"], log, rows, t0, dt)
        T = tec.read_C()
        setpoints["C"] = max(T - 2.0, tec.min_C)
        print(f"C: cool, set point {setpoints['C']:.2f} C")
        run_phase(tec, "C", dur["C"], setpoints["C"], log, rows, t0, dt)
        setpoints["D"] = a.hold_C
        print(f"D: hold {a.hold_C:g} C")
        run_phase(tec, "D", dur["D"], a.hold_C, log, rows, t0, dt)
        ended = "completed"
    except KeyboardInterrupt:
        ended = "stopped by user"
        print("\nStopped.")
    except TECError as exc:
        ended = f"error: {exc}"
        print(f"\n{exc}")
    finally:
        log.close()
        try:
            if "error" not in ended:
                tec.set_C(a.hold_C)
                tec.enable()
        finally:
            tec.close()

    stats = {ph: summarise(rows, ph) for ph in "ABCD"}
    stats = {k: v for k, v in stats.items() if v}
    ver = verdicts(stats, setpoints)
    write_meta(run, {"kind": "tec_diagnostic", "ended": ended, "setpoints_C": setpoints, "phase_seconds": dur,
                     "stats": stats, "verdicts": ver})
    names = {"A": "TEC off", "B": "heat", "C": "cool", "D": f"hold {a.hold_C:g} C"}
    hdr = ("| Phase | Set point (C) | Start (C) | End (C) | Change (C) | Rate (C/min) | Mean TEC (mA) | "
           "Last-2-min spread (C) | Verdict |")
    lines = [f"# TEC diagnostic ({ended})", "", hdr, "|" + "---|" * 9]
    for ph, s in stats.items():
        spt = "off" if setpoints.get(ph) is None else f"{setpoints[ph]:.2f}"
        im = "-" if s["I_mean_mA"] is None else f"{s['I_mean_mA']:+.0f}"
        lines.append(f"| {ph} {names[ph]} | {spt} | {s['T_start']:.2f} | {s['T_end']:.2f} | {s['dT']:+.2f} | "
                     f"{s['rate_C_per_min']:+.2f} | {im} | {s['tail_p2p_C']:.3f} | {ver.get(ph, '')} |")
    (run / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = np.array([r["t_s"] for r in rows], float)
    T = np.array([r["temperature_C"] for r in rows], float)
    sp = np.array([np.nan if r["setpoint_C"] == "" else r["setpoint_C"] for r in rows], float)
    I = np.array([np.nan if r["tec_mA"] == "" else r["tec_mA"] for r in rows], float)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True)
    ax.plot(t, T, color="#1f4e8c", label="laser temperature")
    ax.plot(t, sp, "--", color="#d1495b", label="set point")
    ax.set_ylabel("Temperature (C)")
    ax.legend(fontsize=8)
    ax2.plot(t, I, color="#2a9d8f")
    ax2.axhline(0, color="#555", lw=0.8)
    ax2.set_ylabel("TEC current (mA)\n+ heating, - cooling")
    ax2.set_xlabel("Time (s)")
    for ph in stats:
        ts = [r["t_s"] for r in rows if r["phase"] == ph]
        for axx in (ax, ax2):
            axx.axvline(ts[0], color="#aaa", lw=0.8)
        ax.text(ts[0], ax.get_ylim()[1], f" {ph}", va="top", fontsize=9)
    for axx in (ax, ax2):
        axx.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(run / "tec_diagnostic.png", dpi=150)
    print(f"\nSaved {run}\nTEC left {'holding ' + format(a.hold_C, 'g') + ' C' if 'error' not in ended else 'OFF'}.")
    (run / "stats.json").write_text(json.dumps({"stats": stats, "verdicts": ver}, indent=2))


if __name__ == "__main__":
    main()
