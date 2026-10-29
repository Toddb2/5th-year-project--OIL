"""End-of-campaign report: every figure and the key numbers from each stage, in one place.

Writes into the campaign folder:
  report.html    open in a browser (figures linked relative to the folder, so keep it together)
  report.md      the same for GitHub or VS Code preview
  summary.json   the numbers, for the dissertation tables
  figures/       summary plots made here (pulse width and jitter against bias, locking windows)
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np


def _load(p: Path):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def _rel(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace("\\", "/")


def _num(x, fmt="{:.3g}"):
    if x is None:
        return "-"
    try:
        if isinstance(x, float) and np.isnan(x):
            return "-"
        return fmt.format(x)
    except (TypeError, ValueError):
        return str(x)


class _Doc:
    def __init__(self, base: Path):
        self.base = base
        self.html: list[str] = []
        self.md: list[str] = []

    def h(self, text, level=2):
        self.html.append(f"<h{level}>{html.escape(text)}</h{level}>")
        self.md.append(f"\n{'#' * level} {text}\n")

    def p(self, text):
        self.html.append(f"<p>{html.escape(text)}</p>")
        self.md.append(f"{text}\n")

    def table(self, header, rows):
        if not rows:
            return
        th = "".join(f"<th>{html.escape(str(h))}</th>" for h in header)
        trs = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
        self.html.append(f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
        self.md.append("| " + " | ".join(map(str, header)) + " |")
        self.md.append("|" + "---|" * len(header))
        for r in rows:
            self.md.append("| " + " | ".join(map(str, r)) + " |")
        self.md.append("")

    def figs(self, paths, caption=""):
        paths = [p for p in paths if p and Path(p).exists()]
        if not paths:
            return
        imgs = "".join(f'<figure><a href="{_rel(p, self.base)}"><img src="{_rel(p, self.base)}"></a>'
                       f"<figcaption>{html.escape(caption or Path(p).parent.name)}</figcaption></figure>" for p in paths)
        self.html.append(f'<div class="figs">{imgs}</div>')
        for p in paths:
            self.md.append(f"![{caption or Path(p).parent.name}]({_rel(p, self.base)})")
        self.md.append("")


def _step_runs(state, prefix):
    out = []
    for sid, rec in state["done"].items():
        if sid.startswith(prefix) and rec.get("status") == "ok":
            for r in rec.get("runs", []):
                out.append((sid, rec, Path(r)))
    return out


def build_report(c) -> Path:
    base = c.folder
    figdir = base / "figures"
    figdir.mkdir(exist_ok=True)
    state = c.state
    doc = _Doc(base)
    summary: dict = {"campaign": base.name, "mode": c.mode, "built": datetime.now().isoformat(timespec="seconds")}

    doc.h(f"OIL 852 nm campaign: {base.name}", 1)
    doc.p(f"Mode: {c.mode}. Built {summary['built']}." + (" SIMULATED DATA - not measurements." if c.sim else ""))

    # ---- steps overview ------------------------------------------------------------
    doc.h("Steps")
    doc.table(["step", "what", "status", "time (s)"],
              [(sid, r.get("title", ""), r.get("status", ""), r.get("seconds", "")) for sid, r in state["done"].items()])

    # ---- stage 1 ---------------------------------------------------------------------
    liv = _step_runs(state, "c.liv.")
    if liv or _step_runs(state, "c."):
        doc.h("Stage 1: characterisation")
    rows, figs = [], []
    for sid, rec, run in liv:
        res = _load(run / "results.json") or {}
        meta = _load(run / "meta.json") or {}
        rows.append((_num(meta.get("tec_setpoint_C"), "{:g}"), _num(res.get("threshold_fit_mA"), "{:.1f}"),
                     _num(res.get("threshold_d2_mA"), "{:.1f}"), _num(res.get("slope_W_per_A"), "{:.3f}"),
                     _num(res.get("max_power_mW"), "{:.2f}"), _num(res.get("series_resistance_ohm"), "{:.2f}"),
                     res.get("stop_reason", "")))
        figs.append(run / "liv.png")
        summary.setdefault("liv", []).append({"temperature_C": meta.get("tec_setpoint_C"), **res, "run": str(run)})
    doc.table(["T (C)", "I_th fit (mA)", "I_th kink (mA)", "slope (W/A)", "P max (mW)", "R_s (ohm)", "ended"], rows)
    doc.figs(figs, "L-I-V")
    for sid, rec, run in _step_runs(state, "c.tseries"):
        s = _load(run / "summary.json") or {}
        summary["T0_K"] = s.get("T0_K")
        doc.p(f"Characteristic temperature T0 = {_num(s.get('T0_K'), '{:.0f}')} K")
        doc.figs([run / "temperature_series.png"], "threshold against temperature")
    for sid, rec, run in _step_runs(state, "c.stability"):
        try:
            import pandas as pd
            df = pd.read_csv(run / "stability.csv")
            mean, cv = df.power_mW.mean(), df.power_mW.std() / df.power_mW.mean() * 100
            summary["stability"] = {"mean_mW": float(mean), "std_pct": float(cv), "run": str(run)}
            doc.p(f"Power stability: mean {mean:.4f} mW, standard deviation {cv:.3f} % over {df.elapsed_s.max() / 60:.1f} min")
        except Exception:
            pass
        doc.figs([run / "stability.png"], "power stability")
    tune_runs = _step_runs(state, "c.tuning.")
    if tune_runs:
        folder = tune_runs[-1][2]
        res_files = sorted(folder.glob("*_results.json"))
        if res_files:
            res = _load(res_files[0]) or {}
            summary["tuning"] = res
            doc.table(["T (C)", "current tuning (pm/mA)"],
                      [(k, _num(v * 1000, "{:.2f}")) for k, v in res.get("per_current", {}).items()])
            per_T = list(res.get("per_temperature", {}).values())
            if per_T:
                doc.p(f"Temperature tuning: {np.mean(per_T):.4f} nm/C on average "
                      f"({min(per_T):.4f} to {max(per_T):.4f} nm/C across {len(per_T)} currents)")
            if res.get("mode_hops"):
                doc.p(f"{len(res['mode_hops'])} mode hop(s) flagged: " + "; ".join(
                    f"{h['temperature_C']:g} C, {h['between_mA'][0]:g}-{h['between_mA'][1]:g} mA ({h['jump_nm'] * 1000:.0f} pm)"
                    for h in res["mode_hops"]))
            doc.figs(sorted(folder.glob("*.png")), "wavelength tuning")

    res_dir = c.value("characterisation_results")
    if res_dir and (Path(res_dir) / "results.md").exists():
        doc.p(f"Stage 1 results figures (PNG + PDF) and table: {res_dir}")
        doc.figs([Path(res_dir) / f"{n}.png" for n in ("fig_LI", "fig_threshold_T", "fig_IV")], "stage 1 results")

    # ---- stage 2 ---------------------------------------------------------------------
    if _step_runs(state, "l."):
        doc.h("Stage 2: injection locking")
    for sid, rec, run in _step_runs(state, "l.voa"):
        lk = _load(run / "lookup.json") or {}
        summary["voa"] = {"max_attenuation_dB": lk.get("max_attenuation_dB"), "run": str(run)}
        doc.p(f"VOA: up to {_num(lk.get('max_attenuation_dB'), '{:.1f}')} dB. Voltage every 5 dB: "
              + ", ".join(f"{k} = {v} V" for k, v in lk.get("voltage_for_attenuation", {}).items()))
        doc.figs([run / "voa.png"], "VOA calibration")
    for sid, rec, run in _step_runs(state, "l.spectra"):
        sr = _load(run / "spectra_results.json") or {}
        summary["spectra"] = sr
        doc.table(["trace", "peak (nm)", "SMSR (dB)", "modes within 20 dB", "locked?"],
                  [(k, _num(v.get("peak_nm"), "{:.4f}"), _num(v.get("smsr_dB"), "{:.1f}"),
                    v.get("n_modes_within_20dB"), "yes" if v.get("looks_locked") else "no") for k, v in sr.items()])
        doc.figs([run / "spectra.png"], "OSA spectra")
    maps = _step_runs(state, "l.map.")
    rows, figs, pts = [], [], []
    for sid, rec, run in maps:
        sm = _load(run / "summary.json") or {}
        meta = _load(run / "meta.json") or {}
        widths = sm.get("window_widths_GHz", [])
        rows.append((_num(meta.get("slave_mA"), "{:g}"), _num(meta.get("voa_dB"), "{:g}"), len(sm.get("windows_mA", [])),
                     ", ".join(f"{a:g}-{b:g}" for a, b in sm.get("windows_mA", [])) or "none",
                     ", ".join(f"{w:.2f}" for w in widths) or "-"))
        figs.append(run / "locking_map.png")
        if widths:
            pts.append((float(meta.get("voa_dB")), float(np.mean(widths)), float(meta.get("slave_mA"))))
        summary.setdefault("locking_maps", []).append({"slave_mA": meta.get("slave_mA"), "voa_dB": meta.get("voa_dB"),
                                                       **sm, "run": str(run)})
    doc.table(["slave (mA)", "VOA (dB)", "windows", "locked master currents (mA)", "window widths (GHz)"], rows)
    if pts:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 4))
        for Is in sorted({p[2] for p in pts}):
            xs = [p for p in pts if p[2] == Is]
            ax.plot([-p[0] for p in xs], [p[1] for p in xs], "o-", label=f"slave {Is:g} mA")
        ax.set_xlabel("Relative injection (-VOA attenuation, dB)")
        ax.set_ylabel("Mean locked window (GHz)")
        ax.set_yscale("log")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
        ax.set_title("Locking range against injection")
        fig.tight_layout()
        fig.savefig(figdir / "locking_width_vs_injection.png", dpi=150)
        plt.close(fig)
        doc.figs([figdir / "locking_width_vs_injection.png"], "locking range against injection")
    doc.figs(figs, "locking map")
    for sid, rec, run in _step_runs(state, "l.theory"):
        summary["locking_theory"] = _load(run / "locking_theory.json")
        doc.figs([run / "locking_range.png"], "locking range: theory (bands) and measured (points)")

    # ---- stage 3 ---------------------------------------------------------------------
    scope = _step_runs(state, "p.scope.")
    if scope:
        doc.h("Stage 3: pulsed operation")
    rows, figs, pts = [], [], []
    for sid, rec, run in scope:
        sm = _load(run / "summary.json") or {}
        s = sm.get("summary", {})
        Ib = rec.get("slave_bias_mA")
        rows.append((_num(Ib, "{:g}"), _num(s.get("period_ns", {}).get("mean"), "{:.3f}"),
                     _num(s.get("fwhm_ps", {}).get("mean"), "{:.0f}"), _num(s.get("timing_jitter_ps", {}).get("mean"), "{:.1f}"),
                     _num(s.get("amplitude_cv_pct", {}).get("mean"), "{:.1f}")))
        figs.append(run / "trace.png")
        if s and Ib is not None:
            pts.append((float(Ib), s["fwhm_ps"]["mean"], s["fwhm_ps"]["std"], s["timing_jitter_ps"]["mean"],
                        s["timing_jitter_ps"]["std"]))
        summary.setdefault("pulses", []).append({"slave_bias_mA": Ib, **s, "run": str(run)})
    doc.table(["slave bias (mA)", "period (ns)", "FWHM (ps)", "jitter (ps)", "amplitude spread (%)"], rows)
    if len(pts) >= 2:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        pts.sort()
        b = np.array(pts)
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.errorbar(b[:, 0], b[:, 1], b[:, 2], fmt="o-", capsize=3, label="FWHM")
        ax.set_xlabel("Slave DC bias (mA)")
        ax.set_ylabel("Pulse FWHM (ps)")
        ax2 = ax.twinx()
        ax2.errorbar(b[:, 0], b[:, 3], b[:, 4], fmt="s--", color="#d1495b", capsize=3, label="timing jitter")
        ax2.set_ylabel("Timing jitter (ps)", color="#d1495b")
        ax.grid(alpha=0.3)
        ax.set_title("Gain-switched slave pulses")
        fig.tight_layout()
        fig.savefig(figdir / "pulses_vs_bias.png", dpi=150)
        plt.close(fig)
        doc.figs([figdir / "pulses_vs_bias.png"], "pulse width and jitter against bias")
    doc.figs(figs, "pulse trace")

    # ---- stage 4 ---------------------------------------------------------------------
    if _step_runs(state, "q."):
        doc.h("Stage 4: QKD")
    rows = []
    for key in ("cow", "dps"):
        r = c.value(f"qber_{key}")
        if r:
            summary[f"qber_{key}"] = r
            q = r.get("data_qber_pct") if key == "cow" else r.get("dps_qber_pct")
            rows.append((key.upper(), _num(q, "{:.2f}"), _num(r.get("visibility"), "{:.3f}"),
                         r.get("data_bits_compared") or r.get("bits_compared")))
    doc.table(["protocol", "QBER (%)", "visibility", "bits compared"], rows)
    for sid, rec, run in _step_runs(state, "q.") :
        if sid.endswith(".pattern"):
            doc.figs([run / "pattern.png"], f"{sid.split('.')[1].upper()} drive pattern")
    for sid, rec, run in _step_runs(state, "q.keyrate"):
        kr = _load(run / "keyrate_report.json") or {}
        summary["keyrate"] = {"visibility_used": rec.get("visibility_used"), **kr}
        doc.table(["fibre", "total transmittance", "optimal mu", "secure key (bit/s)", "QBER at mu = 0.1 (%)"],
                  [(k, _num(v["eta_total"], "{:.2e}"), _num(v["optimal_mu"], "{:.2f}"),
                    _num(v["secure_key_bps"], "{:,.0f}"), _num(v["qber_pct_at_mu0.1"], "{:.2f}")) for k, v in kr.items()])
        vis = rec.get("visibility_used")
        doc.p("Key rate uses the measured visibility." if vis else "Key rate uses the default visibility (none measured yet).")
        doc.figs([run / "keyrate_vs_distance.png"], "key rate against fibre length")

    (base / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    css = ("body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;"
           "color:#1d2733;background:#fff}h1{font-size:1.6rem}h2{border-bottom:1px solid #ccd;padding-bottom:4px;"
           "margin-top:2em}table{border-collapse:collapse;margin:10px 0;font-size:.9rem}td,th{border:1px solid #ccd;"
           "padding:4px 8px;text-align:left}th{background:#eef2f7}.figs{display:flex;flex-wrap:wrap;gap:12px}"
           "figure{margin:0;width:340px}figure img{width:100%;border:1px solid #dde}figcaption{font-size:.8rem;color:#556}")
    (base / "report.html").write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><title>OIL campaign {html.escape(base.name)}</title>"
        f"<style>{css}</style></head><body>{''.join(doc.html)}</body></html>", encoding="utf-8")
    (base / "report.md").write_text("\n".join(doc.md), encoding="utf-8")
    return base / "report.html"
