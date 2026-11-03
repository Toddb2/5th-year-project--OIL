"""FP slave laser (FPL852P) below threshold: what the 230 mA KLD101 can measure before the 1 A driver arrives.

  python 01_characterisation/fp_subthreshold.py                                  # every FPL852P L-I-V run in data/
  python 01_characterisation/fp_subthreshold.py --spectra fp_100mA.csv@100 fp_200mA.csv@200
  python 01_characterisation/fp_subthreshold.py --demo                           # synthetic data, to see the output

Measurements (laser threshold 240-300 mA, so everything up to 200 mA is spontaneous emission):
  1. L-I-V with li_sweep.py:  python 01_characterisation/li_sweep.py --laser FPL852P --temp 25 --stop 200 --zero
  2. OSA traces at a few currents (e.g. 100, 150, 200 mA), exported as CSV; label each with @current.

What it works out:
  - I-V: diode fit V = V0 + n kT/q ln(I) + I Rs  ->  series resistance and ideality factor
  - light: spontaneous-emission power, its growth exponent d ln P / d ln I (rises towards threshold as
    gain builds up), and whether lasing started (kink) inside the sweep
  - monitor photodiode response, if it was read
  - OSA: FP mode spacing -> cavity length L = lambda^2 / (2 n_g d_lambda) and free spectral range,
    the numbers stage 2 needs ([injection] slave_mode_spacing_nm)

Writes figures (PNG + PDF), results.md and results.json to results/characterisation/<date>_FPL852P_subthreshold/.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from oil852.config import DATA_ROOT, REPO_ROOT, laser_spec, load_config  # noqa: E402
from oil852.spectrum import analyse_spectrum, load_spectrum, synthetic_fp  # noqa: E402

C = 299_792_458.0
KB_Q = 8.617333e-5  # Boltzmann constant / electron charge, V/K
STYLE = {"figure.dpi": 150, "savefig.dpi": 300, "font.size": 10, "legend.fontsize": 8, "axes.grid": True,
         "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False, "savefig.bbox": "tight"}


def _save(fig, out, name, made):
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}")
    plt.close(fig)
    made.append(name)


def find_runs(laser):
    return sorted(p.parent for p in DATA_ROOT.rglob(f"{laser}_LIV_*/liv.csv")
                  if "_sim" not in str(p) and "demo" not in str(p))


def fit_iv(I_mA, V, temp_C=25.0):
    """V = V0 + n Vt ln(I) + I Rs, least squares over the points above 1 mA."""
    I = np.asarray(I_mA, float) / 1000
    V = np.asarray(V, float)
    sel = (I > 1e-3) & np.isfinite(V) & (V > 0.2)
    if sel.sum() < 5:
        return None
    A = np.column_stack([np.ones(sel.sum()), np.log(I[sel]), I[sel]])
    (V0, a, Rs), *_ = np.linalg.lstsq(A, V[sel], rcond=None)
    Vt = KB_Q * (temp_C + 273.15)
    pred = A @ np.array([V0, a, Rs])
    return {"V0_V": float(V0), "ideality_n": float(a / Vt), "series_resistance_ohm": float(Rs),
            "rms_residual_mV": float(np.sqrt(np.mean((pred - V[sel]) ** 2)) * 1000)}


def light_analysis(I, P):
    """Spontaneous-emission growth and a lasing check."""
    I = np.asarray(I, float)
    P = np.asarray(P, float)
    ok = (I > 5) & (P > 0)
    out = {"max_power_mW": float(P.max()), "current_at_max_mA": float(I[np.argmax(P)])}
    if ok.sum() >= 6:
        lI, lP = np.log(I[ok]), np.log(P[ok])
        k = np.gradient(lP, lI)
        k = pd.Series(k).rolling(5, center=True, min_periods=1).median().to_numpy()
        out["exponent_I"] = I[ok].tolist()
        out["exponent"] = k.tolist()
        out["exponent_low"] = float(np.median(k[: max(3, len(k) // 4)]))
        out["exponent_high"] = float(np.median(k[-max(3, len(k) // 4):]))
    # lasing: slope after the kink much steeper than before
    lasing = None
    if len(I) >= 10:
        grid = np.arange(I.min(), I.max() + 0.5, 1.0)
        Pg = np.interp(grid, I, P)
        s = np.gradient(Pg, grid)
        n = len(s) // 5 or 1
        if s[-n:].mean() > 8 * max(s[:n].mean(), 1e-9) and s[-n:].mean() > 0.05:  # > 0.05 W/A after the kink
            j = int(np.argmax(np.gradient(s, grid)))
            lasing = float(grid[j])
    out["lasing_onset_mA"] = lasing
    return out


def spectra_analysis(items, n_g):
    res = []
    for path, current in items:
        wl, p = load_spectrum(path)
        r = analyse_spectrum(wl, p)
        d = {"file": str(path), "current_mA": current, "peak_nm": r.peak_nm, "peak_dBm": r.peak_dBm,
             "mode_spacing_nm": r.mode_spacing_nm, "modes_within_20dB": r.n_modes_within_20dB}
        if r.mode_spacing_nm:
            lam = r.peak_nm * 1e-9
            dl = r.mode_spacing_nm * 1e-9
            d["fsr_GHz"] = C * dl / lam ** 2 / 1e9
            d["cavity_length_mm"] = lam ** 2 / (2 * n_g * dl) * 1000
        res.append((d, wl, p))
    return res


def make_demo(folder: Path, spec):
    """Synthetic FPL852P sub-threshold data in the same format as li_sweep.py and an OSA export."""
    from oil852.instruments.sim import SimLaser
    folder.mkdir(parents=True, exist_ok=True)
    las = SimLaser(ith_25C_mA=spec.threshold_typ_mA, slope_W_per_A=spec.slope_typ_W_per_A, r_series=1.2,
                   v_turn_on=1.45)
    rows = []
    for I in np.arange(0, 201, 2.0):
        # spontaneous emission that grows superlinearly as the gain builds towards threshold
        P = 0.02 * (I / 200) ** 1.6 * (1 + 0.5 * (I / spec.threshold_typ_mA) ** 6) if I > 0 else 0.0
        rows.append({"set_mA": I, "current_mA": I, "power_mW": P, "power_std_mW": 0.0, "voltage_V": las.voltage_V(I),
                     "pd_mA": P * 0.01, "elapsed_s": 0})
    run = folder / "FPL852P_LIV_25C_demo"
    run.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(run / "liv.csv", index=False)
    (run / "meta.json").write_text(json.dumps({"laser": "FPL852P", "tec_setpoint_C": 25.0}))
    traces = []
    for I, h in ((100, 0), (200, 6)):
        wl, p = synthetic_fp(False, centre_nm=852.3, spacing_nm=0.11, n=13, seed=I)
        f = folder / f"fp_{I}mA.csv"
        pd.DataFrame({"wavelength_nm": wl, "power_dBm": p + h - 25}).to_csv(f, index=False)
        traces.append((f, float(I)))
    return [run], traces


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=Path, nargs="*", default=None, help="FPL852P L-I-V run folders (default: all)")
    p.add_argument("--spectra", nargs="*", default=[], help="OSA CSV exports, each as file.csv@current_mA")
    p.add_argument("--group-index", type=float, default=3.6, help="group index of the FP chip (GaAs/AlGaAs ~3.6-4)")
    p.add_argument("--laser", default="FPL852P")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--demo", action="store_true", help="synthetic data, to see what the output looks like")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    plt.rcParams.update(STYLE)
    spec = laser_spec(load_config(a.config), a.laser)

    if a.demo:
        demo = DATA_ROOT / "demo_fp"
        runs, traces = make_demo(demo, spec)
        out = a.out or demo / "results"
    else:
        runs = a.runs if a.runs else find_runs(a.laser)
        traces = []
        for item in a.spectra:
            path, _, cur = item.partition("@")
            traces.append((Path(path), float(cur) if cur else None))
        out = a.out or REPO_ROOT / "results" / "characterisation" / f"{datetime.now():%Y-%m-%d}_{a.laser}_subthreshold"
    if not runs and not traces:
        _sys.exit(f"No {a.laser} L-I-V runs found and no spectra given. Run li_sweep.py --laser {a.laser} first, or --demo.")
    out.mkdir(parents=True, exist_ok=True)
    made, results = [], {"laser": a.laser, "made": datetime.now().isoformat(timespec="seconds"),
                         "threshold_spec_mA": "240-300", "group_index_used": a.group_index, "runs": []}

    curves = []
    for r in runs:
        r = Path(r)
        df = pd.read_csv(r / "liv.csv").dropna(subset=["current_mA", "power_mW"]).sort_values("current_mA")
        meta = json.loads((r / "meta.json").read_text()) if (r / "meta.json").exists() else {}
        T = float(meta.get("tec_setpoint_C", 25.0))
        iv = fit_iv(df["current_mA"], df["voltage_V"], T) if "voltage_V" in df else None
        li = light_analysis(df["current_mA"], df["power_mW"])
        pdr = None
        if "pd_mA" in df and df["pd_mA"].notna().sum() >= 5 and df["pd_mA"].abs().max() > 0:
            d = df.dropna(subset=["pd_mA"])
            pdr = float(np.polyfit(d["power_mW"], d["pd_mA"], 1)[0] * 1000)
        curves.append((T, df, iv, li, pdr, r))
        results["runs"].append({"run": str(r), "temperature_C": T, "iv": iv, "pd_uA_per_mW": pdr,
                                **{k: v for k, v in li.items() if not k.startswith("exponent_I") and k != "exponent"}})

    if curves:
        temps = [c[0] for c in curves]
        cmap = plt.get_cmap("plasma")
        col = lambda T: cmap(0.1 + 0.75 * ((T - min(temps)) / ((max(temps) - min(temps)) or 1)))  # noqa: E731
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.8))
        for T, df, iv, li, pdr, r in curves:
            ax.plot(df["current_mA"], df["power_mW"] * 1000, "-", color=col(T), label=f"{T:g} °C")
            pos = df[df["power_mW"] > 0]
            ax2.loglog(pos["current_mA"], pos["power_mW"] * 1000, "o", ms=2.5, color=col(T), label=f"{T:g} °C")
            if li["lasing_onset_mA"]:
                ax.axvline(li["lasing_onset_mA"], color=col(T), ls=":", lw=1)
        ax.set_xlabel("Drive current (mA)")
        ax.set_ylabel("Output power (µW)")
        ax.set_title("Below threshold (spontaneous emission)")
        ax.legend()
        ax2.set_xlabel("Drive current (mA)")
        ax2.set_ylabel("Output power (µW)")
        ax2.set_title("Log–log")
        _save(fig, out, "fig_FP_LI", made)

        fig, ax = plt.subplots(figsize=(5.5, 3.8))
        for T, df, iv, li, pdr, r in curves:
            if "exponent" in li:
                ax.plot(li["exponent_I"], li["exponent"], "-", color=col(T), label=f"{T:g} °C")
        ax.axhline(1, color="#888", ls="--", lw=0.8)
        ax.set_xlabel("Drive current (mA)")
        ax.set_ylabel("d ln P / d ln I")
        ax.set_title("Emission growth exponent (rises as gain approaches threshold)")
        ax.legend()
        _save(fig, out, "fig_FP_exponent", made)

        ref = min(curves, key=lambda c: abs(c[0] - 25))
        T, df, iv, li, pdr, r = ref
        if iv:
            d = df.dropna(subset=["voltage_V"])
            d = d[d["current_mA"] > 0]
            fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.8))
            ax.plot(d["current_mA"], d["voltage_V"], "o", ms=2.5, color="#333", label="measured")
            x = np.linspace(max(d["current_mA"].min(), 1), d["current_mA"].max(), 200)
            Vt = KB_Q * (T + 273.15)
            ax.plot(x, iv["V0_V"] + iv["ideality_n"] * Vt * np.log(x / 1000) + iv["series_resistance_ohm"] * x / 1000,
                    "-", color="#d1495b", lw=1,
                    label=f"fit: n = {iv['ideality_n']:.2f}, $R_s$ = {iv['series_resistance_ohm']:.2f} Ω")
            ax.set_xlabel("Drive current (mA)")
            ax.set_ylabel("Forward voltage (V)")
            ax.set_title(f"I–V at {T:g} °C")
            ax.legend(loc="lower right")
            dv = np.gradient(d["voltage_V"].to_numpy(float), d["current_mA"].to_numpy(float) / 1000)
            ax2.plot(d["current_mA"], dv, "-", color="#1f4e8c")
            ax2.set_xlabel("Drive current (mA)")
            ax2.set_ylabel("dV/dI (Ω)")
            ax2.set_ylim(0, min(np.nanpercentile(dv, 95) * 1.5, 200))
            ax2.set_title("Differential resistance")
            _save(fig, out, "fig_FP_IV", made)
        if pdr is not None:
            d = df.dropna(subset=["pd_mA"])
            fig, ax = plt.subplots(figsize=(5.5, 3.8))
            ax.plot(d["power_mW"] * 1000, d["pd_mA"] * 1000, "o", ms=2.5, color="#1f4e8c")
            ax.set_xlabel("Output power (µW)")
            ax.set_ylabel("Monitor photodiode (µA)")
            ax.set_title(f"{pdr:.1f} µA/mW")
            _save(fig, out, "fig_FP_monitor_PD", made)

    spec_res = spectra_analysis(traces, a.group_index) if traces else []
    if spec_res:
        fig, ax = plt.subplots(figsize=(8, 4))
        for k, (d, wl, pw) in enumerate(spec_res):
            lab = f"{d['current_mA']:g} mA" if d["current_mA"] is not None else Path(d["file"]).stem
            if d.get("mode_spacing_nm"):
                lab += f": spacing {d['mode_spacing_nm'] * 1000:.1f} pm"
            ax.plot(wl, pw, lw=0.8, label=lab)
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Power (dBm)")
        ax.set_title("FP mode comb below threshold")
        ax.legend()
        _save(fig, out, "fig_FP_spectra", made)
        results["spectra"] = [d for d, *_ in spec_res]
        sp = [d["mode_spacing_nm"] for d, *_ in spec_res if d.get("mode_spacing_nm")]
        if sp:
            results["mode_spacing_nm"] = float(np.median(sp))
            results["cavity_length_mm"] = float(np.median([d["cavity_length_mm"] for d, *_ in spec_res
                                                           if d.get("cavity_length_mm")]))
            results["fsr_GHz"] = float(np.median([d["fsr_GHz"] for d, *_ in spec_res if d.get("fsr_GHz")]))

    lines = [f"# {a.laser} below threshold", "", f"Made {datetime.now():%d %b %Y %H:%M}. Spec threshold 240–300 mA.", ""]
    if curves:
        lines += ["| T (°C) | Max current (mA) | Power there (µW) | Emission exponent (low → high I) | Lasing in sweep? | "
                  "R_s (Ω) | Ideality n | Monitor PD (µA/mW) |", "|---|---|---|---|---|---|---|---|"]
        for T, df, iv, li, pdr, r in curves:
            ex = f"{li.get('exponent_low', float('nan')):.2f} → {li.get('exponent_high', float('nan')):.2f}" if "exponent" in li else "-"
            las = f"yes, from ~{li['lasing_onset_mA']:.0f} mA" if li["lasing_onset_mA"] else f"no (threshold > {df['current_mA'].max():.0f} mA)"
            lines.append(f"| {T:g} | {df['current_mA'].max():.0f} | {li['max_power_mW'] * 1000:.1f} | {ex} | {las} | "
                         f"{iv['series_resistance_ohm']:.2f} | {iv['ideality_n']:.2f} | " if iv else
                         f"| {T:g} | {df['current_mA'].max():.0f} | {li['max_power_mW'] * 1000:.1f} | {ex} | {las} | - | - | ")
            lines[-1] += f"{pdr:.1f} |" if pdr is not None else "- |"
        lines.append("")
    if spec_res:
        lines += ["| Trace | Current (mA) | Peak (nm) | Mode spacing (pm) | FSR (GHz) | Cavity length (mm) |",
                  "|---|---|---|---|---|---|"]
        for d, *_ in spec_res:
            cur = f"{d['current_mA']:g}" if d["current_mA"] is not None else "-"
            sp = f"{d['mode_spacing_nm'] * 1000:.1f}" if d.get("mode_spacing_nm") else "-"
            fsr = f"{d['fsr_GHz']:.1f}" if d.get("fsr_GHz") else "-"
            L = f"{d['cavity_length_mm']:.2f}" if d.get("cavity_length_mm") else "-"
            lines.append(f"| {Path(d['file']).name} | {cur} | {d['peak_nm']:.3f} | {sp} | {fsr} | {L} |")
        lines.append("")
        if results.get("mode_spacing_nm"):
            lines += [f"Cavity length uses n_g = {a.group_index:g}. For stage 2 set `[injection] slave_mode_spacing_nm = "
                      f"{results['mode_spacing_nm']:.4f}` in config/bench.toml.", ""]
    lines += ["## Figures", ""] + [f"- `{m}.png` / `{m}.pdf`" for m in made]
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n".join(lines))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
