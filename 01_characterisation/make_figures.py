"""Make the stage 1 results: dissertation-ready figures (PNG + PDF) and a results table.

  python 01_characterisation/make_figures.py                         # every L-I-V run in data/ for the DBR852PN
  python 01_characterisation/make_figures.py --campaign data/campaigns/<folder>
  python 01_characterisation/make_figures.py --runs data/2026-10-29/DBR852PN_LIV_25C_*  --tuning data/tuning.csv

Writes to results/characterisation/<date>_<laser>/ (or --out):
  fig_LI          L-I at every temperature, with the threshold fits
  fig_dPdI        differential efficiency and the threshold kink
  fig_IV          forward voltage, series resistance and wall-plug efficiency (if voltage was read)
  fig_threshold_T threshold and slope efficiency against temperature, with T0 (two or more temperatures)
  fig_monitor_PD  monitor photodiode current against output power (if the photodiode was read)
  fig_stability   power against time and relative deviation (if a stability run is given)
  fig_tuning      wavelength against current and temperature (if a tuning CSV is given)
  results.csv     one row per temperature
  results.md      summary table against the spec sheet, and the list of figures
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

from oil852.analysis import analyse_li, characteristic_temperature, load_li, tuning_coefficients  # noqa: E402
from oil852.config import DATA_ROOT, REPO_ROOT, laser_spec, load_config  # noqa: E402

STYLE = {"figure.dpi": 150, "savefig.dpi": 300, "font.size": 10, "axes.labelsize": 10, "axes.titlesize": 10,
         "legend.fontsize": 8, "axes.grid": True, "grid.alpha": 0.3, "lines.linewidth": 1.4,
         "axes.spines.top": False, "axes.spines.right": False, "savefig.bbox": "tight"}
CMAP = plt.get_cmap("plasma")


def _colour(T, temps):
    lo, hi = min(temps), max(temps)
    return CMAP(0.1 + 0.75 * ((T - lo) / (hi - lo) if hi > lo else 0.5))


def _save(fig, out: Path, name: str, made: list):
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}")
    plt.close(fig)
    made.append(name)


# ---- finding the data ----------------------------------------------------------------

def runs_from_campaign(folder: Path):
    state = json.loads((folder / "state.json").read_text())
    liv, stab, tune = [], [], None
    for sid, rec in state["done"].items():
        if rec.get("status") != "ok":
            continue
        if sid.startswith("c.liv."):
            liv += [Path(r) for r in rec.get("runs", [])]
        elif sid == "c.stability":
            stab += [Path(r) for r in rec.get("runs", [])]
        elif sid.startswith("c.tuning.") and rec.get("runs"):
            cands = sorted(Path(rec["runs"][-1]).glob("tuning_*.csv"))
            tune = cands[0] if cands else tune
    return liv, (stab[-1] if stab else None), tune


def runs_from_data(laser: str):
    def real(p):
        return "_sim" not in str(p) and "demo" not in str(p)
    liv = [p.parent for p in DATA_ROOT.rglob(f"{laser}_LIV_*/liv.csv") if real(p)]
    stab = sorted((p.parent for p in DATA_ROOT.rglob(f"{laser}_stability_*/stability.csv") if real(p)),
                  key=lambda d: d.name)
    return liv, (stab[-1] if stab else None), None


def load_runs(run_dirs):
    """One curve per temperature: the latest run at each set point."""
    by_T = {}
    for r in run_dirs:
        r = Path(r)
        if not (r / "liv.csv").exists():
            continue
        meta = json.loads((r / "meta.json").read_text()) if (r / "meta.json").exists() else {}
        T = float(meta.get("tec_setpoint_C", np.nan))
        df = load_li(r / "liv.csv")
        try:
            res = analyse_li(df)
        except Exception as exc:
            print(f"  skipped {r.name}: {exc}")
            continue
        key = round(T, 2)
        if key not in by_T or meta.get("created", "") > by_T[key][3].get("created", ""):
            by_T[key] = (df, res, r, meta)
    return dict(sorted(by_T.items()))


# ---- figures ---------------------------------------------------------------------------

def fig_li(curves, out, made):
    temps = list(curves)
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for T, (df, res, run, meta) in curves.items():
        c = _colour(T, temps)
        I, P = df["current_mA"], df["power_mW"]
        ax.plot(I, P, "o", ms=2.5, color=c, label=f"{T:g} °C: $I_{{th}}$ = {res.threshold_fit_mA:.1f} mA, "
                                                  f"$\\eta$ = {res.slope_W_per_A:.3f} W/A")
        x = np.linspace(res.threshold_fit_mA, I.max(), 20)
        ax.plot(x, res.slope_W_per_A * (x - res.threshold_fit_mA), "-", color=c, lw=1, alpha=0.8)
    ax.set_xlabel("Drive current (mA)")
    ax.set_ylabel("Output power (mW)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left")
    _save(fig, out, "fig_LI", made)


def fig_dpdi(curves, ref, out, made):
    df, res, *_ = curves[ref]
    I, P = df["current_mA"].to_numpy(float), df["power_mW"].to_numpy(float)
    grid = np.arange(I.min(), I.max() + 0.25, 0.5)
    Pg = np.interp(grid, I, P)
    dP = np.gradient(Pg, grid)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(6, 5), sharex=True, gridspec_kw={"height_ratios": [1, 1]})
    ax.plot(I, P, "o", ms=2.5, color="#1f4e8c")
    ax.axvline(res.threshold_fit_mA, ls=":", color="#d1495b", lw=1)
    ax.set_ylabel("Output power (mW)")
    ax.set_title(f"{ref:g} °C")
    ax2.plot(grid, dP, color="#1f4e8c")
    ax2.axvline(res.threshold_d2_mA, ls="--", color="#555", lw=1, label=f"kink {res.threshold_d2_mA:.1f} mA")
    ax2.axvline(res.threshold_fit_mA, ls=":", color="#d1495b", lw=1, label=f"linear fit {res.threshold_fit_mA:.1f} mA")
    ax2.set_xlabel("Drive current (mA)")
    ax2.set_ylabel("dP/dI (W/A)")
    ax2.legend(loc="lower right")
    _save(fig, out, "fig_dPdI", made)


def fig_iv(curves, ref, out, made):
    df, res, *_ = curves[ref]
    if "voltage_V" not in df or df["voltage_V"].notna().sum() < 4:
        return
    d = df.dropna(subset=["voltage_V"])
    d = d[d["current_mA"] > 0]
    I, V, P = d["current_mA"].to_numpy(float), d["voltage_V"].to_numpy(float), d["power_mW"].to_numpy(float)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9, 3.6))
    ax.plot(I, V, "o", ms=2.5, color="#333")
    if res.series_resistance_ohm is not None:
        x = np.linspace(res.threshold_fit_mA, I.max(), 20)
        ax.plot(x, res.turn_on_voltage_V + res.series_resistance_ohm * x / 1000, "-", color="#d1495b", lw=1,
                label=f"$R_s$ = {res.series_resistance_ohm:.2f} Ω, $V_0$ = {res.turn_on_voltage_V:.2f} V")
        ax.legend(loc="lower right")
    ax.set_xlabel("Drive current (mA)")
    ax.set_ylabel("Forward voltage (V)")
    ax.set_title(f"I–V at {ref:g} °C")
    with np.errstate(divide="ignore", invalid="ignore"):
        wpe = np.where((V > 0) & (I > 0), P / (I * V) * 100, np.nan)
    ax2.plot(I, wpe, "-", color="#1f4e8c")
    ax2.set_xlabel("Drive current (mA)")
    ax2.set_ylabel("Wall-plug efficiency (%)")
    ax2.set_title(f"Peak {np.nanmax(wpe):.1f} %")
    _save(fig, out, "fig_IV", made)


def fig_threshold_t(curves, out, made):
    if len(curves) < 2:
        return None
    T = np.array(list(curves))
    ith = np.array([v[1].threshold_fit_mA for v in curves.values()])
    eta = np.array([v[1].slope_W_per_A for v in curves.values()])
    T0 = characteristic_temperature(T, ith)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9, 3.6))
    ax.plot(T, ith, "o", color="#1f4e8c")
    if T0 and np.isfinite(T0):
        a, b = np.polyfit(T, np.log(ith), 1)
        x = np.linspace(T.min() - 1, T.max() + 1, 50)
        ax.plot(x, np.exp(b + a * x), "-", color="#d1495b", lw=1, label=f"$T_0$ = {T0:.0f} K")
        ax.legend(loc="upper left")
    ax.set_xlabel("TEC temperature (°C)")
    ax.set_ylabel("Threshold current (mA)")
    ax2.plot(T, eta, "s", color="#2a9d8f")
    ax2.set_xlabel("TEC temperature (°C)")
    ax2.set_ylabel("Slope efficiency (W/A)")
    _save(fig, out, "fig_threshold_T", made)
    return T0


def fig_monitor_pd(curves, ref, out, made):
    df, res, *_ = curves[ref]
    if "pd_mA" not in df or df["pd_mA"].notna().sum() < 4 or res.pd_responsivity_mA_per_mW is None:
        return
    d = df.dropna(subset=["pd_mA"])
    fig, ax = plt.subplots(figsize=(5.5, 3.8))
    ax.plot(d["power_mW"], d["pd_mA"] * 1000, "o", ms=2.5, color="#1f4e8c")
    x = np.linspace(0, d["power_mW"].max(), 20)
    lasing = d[d["current_mA"] > res.threshold_fit_mA]
    b = np.polyfit(lasing["power_mW"], lasing["pd_mA"], 1)[1] if len(lasing) >= 3 else 0.0
    ax.plot(x, (res.pd_responsivity_mA_per_mW * x + b) * 1000, "-", color="#d1495b", lw=1,
            label=f"{res.pd_responsivity_mA_per_mW * 1000:.1f} µA/mW")
    ax.set_xlabel("Output power (mW)")
    ax.set_ylabel("Monitor photodiode current (µA)")
    ax.legend(loc="upper left")
    _save(fig, out, "fig_monitor_PD", made)


def fig_stability(run: Path, out, made):
    df = pd.read_csv(run / "stability.csv")
    if len(df) < 5:
        return None
    meta = json.loads((run / "meta.json").read_text()) if (run / "meta.json").exists() else {}
    t = df["elapsed_s"] / 60
    P = df["power_mW"]
    rel = (P / P.mean() - 1) * 100
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(6, 4.6), sharex=True)
    ax.plot(t, P, color="#1f4e8c", lw=0.8)
    ax.set_ylabel("Power (mW)")
    ax.set_title(f"{meta.get('current_mA', '?')} mA, {meta.get('tec_setpoint_C', '?')} °C")
    ax2.plot(t, rel, color="#555", lw=0.8)
    ax2.axhline(0, color="#d1495b", lw=0.8)
    ax2.set_xlabel("Time (min)")
    ax2.set_ylabel("Deviation from mean (%)")
    _save(fig, out, "fig_stability", made)
    return {"mean_mW": float(P.mean()), "std_pct": float(P.std() / P.mean() * 100),
            "peak_to_peak_pct": float((P.max() - P.min()) / P.mean() * 100), "minutes": float(t.max())}


def fig_tuning(csv: Path, out, made):
    df = pd.read_csv(csv).dropna(subset=["wavelength_nm"])
    if len(df) < 3:
        return None
    res = tuning_coefficients(df)
    temps = sorted(df["temperature_C"].unique())
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9, 3.6))
    for T in temps:
        g = df[df["temperature_C"] == T].sort_values("current_mA")
        k = res["per_current"].get(float(T))
        ax.plot(g["current_mA"], g["wavelength_nm"], "o-", ms=3, color=_colour(T, temps),
                label=f"{T:g} °C" + (f": {k * 1000:.2f} pm/mA" if k else ""))
    for h in res["mode_hops"]:
        ax.axvspan(*h["between_mA"], color="#d1495b", alpha=0.15)
    ax.set_xlabel("Drive current (mA)")
    ax.set_ylabel("Peak wavelength (nm)")
    ax.legend()
    if res["per_temperature"]:
        currents = sorted(res["per_temperature"])
        pick = currents[:: max(1, len(currents) // 4)]
        for I in pick:
            g = df[df["current_mA"] == I].sort_values("temperature_C")
            ax2.plot(g["temperature_C"], g["wavelength_nm"], "s-", ms=3,
                     label=f"{I:g} mA: {res['per_temperature'][I]:.3f} nm/°C")
        ax2.legend()
    ax2.set_xlabel("TEC temperature (°C)")
    ax2.set_ylabel("Peak wavelength (nm)")
    _save(fig, out, "fig_tuning", made)
    return res


# ---- main ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--campaign", type=Path, default=None, help="campaign folder from run_experiment.py")
    p.add_argument("--runs", type=Path, nargs="*", default=None, help="L-I-V run folders")
    p.add_argument("--stability", type=Path, default=None, help="power_stability run folder")
    p.add_argument("--tuning", type=Path, default=None, help="wavelength_log CSV")
    p.add_argument("--laser", default="DBR852PN")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--config", default=None)
    a = p.parse_args()
    plt.rcParams.update(STYLE)
    cfg = load_config(a.config)
    spec = laser_spec(cfg, a.laser)

    if a.campaign:
        liv, stab, tune = runs_from_campaign(a.campaign)
    elif a.runs:
        liv, stab, tune = a.runs, None, None
    else:
        liv, stab, tune = runs_from_data(a.laser)
    stab = a.stability or stab
    tune = a.tuning or tune
    curves = load_runs(liv)
    if not curves:
        _sys.exit("No usable L-I-V runs found. Run 01_characterisation/li_sweep.py first.")
    out = a.out or REPO_ROOT / "results" / "characterisation" / f"{datetime.now():%Y-%m-%d}_{a.laser}"
    out.mkdir(parents=True, exist_ok=True)

    ref = min(curves, key=lambda T: abs(T - 25.0) if np.isfinite(T) else 1e9)
    made: list[str] = []
    fig_li(curves, out, made)
    fig_dpdi(curves, ref, out, made)
    fig_iv(curves, ref, out, made)
    T0 = fig_threshold_t(curves, out, made)
    fig_monitor_pd(curves, ref, out, made)
    stab_res = fig_stability(Path(stab), out, made) if stab else None
    tune_res = fig_tuning(Path(tune), out, made) if tune else None

    rows = []
    for T, (df, res, run, meta) in curves.items():
        rows.append({"temperature_C": T, "threshold_fit_mA": round(res.threshold_fit_mA, 2),
                     "threshold_kink_mA": round(res.threshold_d2_mA, 2), "slope_W_per_A": round(res.slope_W_per_A, 4),
                     "fit_r2": round(res.fit_r2, 5), "max_power_mW": round(res.max_power_mW, 3),
                     "current_at_max_mA": res.current_at_max_mA,
                     "series_resistance_ohm": None if res.series_resistance_ohm is None else round(res.series_resistance_ohm, 3),
                     "turn_on_V": None if res.turn_on_voltage_V is None else round(res.turn_on_voltage_V, 3),
                     "wallplug_peak_pct": None if res.max_wallplug_eff_pct is None else round(res.max_wallplug_eff_pct, 2),
                     "pd_uA_per_mW": None if res.pd_responsivity_mA_per_mW is None else round(res.pd_responsivity_mA_per_mW * 1000, 2),
                     "attenuation_dB": meta.get("attenuation_dB", 0.0), "sweep_ended": "",
                     "run": str(run)})
        rj = run / "results.json"
        if rj.exists():
            rows[-1]["sweep_ended"] = json.loads(rj.read_text()).get("stop_reason", "")
    table = pd.DataFrame(rows)
    table.to_csv(out / "results.csv", index=False)

    r = curves[ref][1]
    k_tune = None
    if tune_res and tune_res["per_current"]:
        k_tune = tune_res["per_current"].get(min(tune_res["per_current"], key=lambda t: abs(t - ref)))
    per_T = list(tune_res["per_temperature"].values()) if tune_res else []
    p_at = lambda I: max(r.slope_W_per_A * (I - r.threshold_fit_mA), 0)  # noqa: E731
    lines = [f"# {a.laser} characterisation results", "",
             f"Made {datetime.now():%d %b %Y %H:%M} from {len(curves)} L–I–V run(s). Reference temperature {ref:g} °C.", "",
             "| Quantity | Spec sheet | Measured |", "|---|---|---|",
             f"| Threshold ({ref:g} °C) | ~{spec.threshold_typ_mA:g} mA | {r.threshold_fit_mA:.1f} mA (fit), {r.threshold_d2_mA:.1f} mA (kink) |",
             f"| Slope efficiency | {spec.slope_typ_W_per_A:g} W/A | {r.slope_W_per_A:.3f} W/A |",
             f"| Power at 200 mA | ~{spec.slope_typ_W_per_A * (200 - spec.threshold_typ_mA):.1f} mW | "
             + (f"{p_at(200):.1f} mW (from the fit)" if r.current_at_max_mA < 200 else f"{float(np.interp(200, curves[ref][0]['current_mA'], curves[ref][0]['power_mW'])):.1f} mW") + " |",
             f"| Series resistance | – | {r.series_resistance_ohm:.2f} Ω |" if r.series_resistance_ohm is not None else "| Series resistance | – | not measured |",
             f"| T0 | – | {T0:.0f} K |" if T0 else "| T0 | – | needs two or more temperatures |",
             f"| Current tuning | ~{spec.extra.get('tuning_typ_nm_per_mA', 0.002) * 1000:g} pm/mA | "
             + (f"{k_tune * 1000:.2f} pm/mA |" if k_tune else "not measured |"),
             f"| Temperature tuning | ~{spec.extra.get('tuning_typ_nm_per_C', 0.06):g} nm/°C | "
             + (f"{np.mean(per_T):.3f} nm/°C |" if per_T else "not measured |"),
             f"| Monitor photodiode | – | {r.pd_responsivity_mA_per_mW * 1000:.1f} µA/mW |" if r.pd_responsivity_mA_per_mW else "| Monitor photodiode | – | not read |"]
    if stab_res:
        lines.append(f"| Power stability | – | {stab_res['std_pct']:.3f} % rms, {stab_res['peak_to_peak_pct']:.2f} % peak-to-peak over {stab_res['minutes']:.0f} min |")
    t2 = table.drop(columns=["run"]).fillna("")
    lines += ["", "## Per temperature", "", "| " + " | ".join(t2.columns) + " |", "|" + "---|" * len(t2.columns)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in t2.itertuples(index=False)] + [""]
    ended = [x for x in table["sweep_ended"] if x and x != "completed"]
    if ended:
        lines += ["Some sweeps stopped early: " + "; ".join(sorted(set(ended))) + ".", ""]
    lines += ["## Figures", ""] + [f"- `{m}.png` / `{m}.pdf`" for m in made] + [""]
    lines += ["Data runs used:", ""] + [f"- `{Path(v[2]).name}`" for v in curves.values()]
    (out / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(made)} figures and the results table saved in {out}")
    for line in lines[4:14]:
        print(line)


if __name__ == "__main__":
    main()
