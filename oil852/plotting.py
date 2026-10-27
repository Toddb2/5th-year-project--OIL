"""Plots for L-I-V curves, temperature series, stability logs and tuning."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .analysis import LIResult  # noqa: E402

plt.rcParams.update({"figure.dpi": 150, "font.size": 10, "axes.grid": True, "grid.alpha": 0.3})


def plot_liv(df, res: LIResult, title: str, path):
    I, P = df["current_mA"].to_numpy(float), df["power_mW"].to_numpy(float)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    ax.plot(I, P, "o", ms=3.5, color="#1f4e8c", label="measured power")
    xs = np.linspace(res.threshold_fit_mA, I.max(), 50)
    ax.plot(xs, res.slope_W_per_A * (xs - res.threshold_fit_mA), "-", color="#d1495b", lw=1.2,
            label=f"fit: $I_{{th}}$ = {res.threshold_fit_mA:.1f} mA, $\\eta$ = {res.slope_W_per_A:.3f} W/A")
    ax.axvline(res.threshold_fit_mA, color="#d1495b", ls=":", lw=1)
    ax.set_ylabel("Optical power (mW)")
    ax.set_title(title)
    if "voltage_V" in df and df["voltage_V"].notna().any():
        axv = ax.twinx()
        dv = df.dropna(subset=["voltage_V"])
        axv.plot(dv["current_mA"], dv["voltage_V"], "-", color="#666", lw=1, label="forward voltage")
        axv.set_ylabel("Voltage (V)", color="#666")
        axv.grid(False)
        lines = ax.get_legend_handles_labels()
        lines2 = axv.get_legend_handles_labels()
        ax.legend(lines[0] + lines2[0], lines[1] + lines2[1], loc="upper left", fontsize=8)
    else:
        ax.legend(loc="upper left", fontsize=8)
    grid = np.linspace(I.min(), I.max(), 300)
    dP = np.gradient(np.interp(grid, I, P), grid)
    ax2.plot(grid, dP, color="#1f4e8c", lw=1)
    ax2.axvline(res.threshold_d2_mA, color="#888", ls="--", lw=1, label=f"kink (d²P/dI² peak) {res.threshold_d2_mA:.1f} mA")
    ax2.set_xlabel("Drive current (mA)")
    ax2.set_ylabel("dP/dI (W/A)")
    ax2.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_temperature_series(curves, t0, path):
    """curves: list of (temperature_C, df, LIResult)."""
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    cmap = plt.get_cmap("plasma")
    temps = [c[0] for c in curves]
    span = (max(temps) - min(temps)) or 1
    for T, df, _ in sorted(curves, key=lambda c: c[0]):
        ax.plot(df["current_mA"], df["power_mW"], "-", lw=1.3, color=cmap(0.85 * (T - min(temps)) / span), label=f"{T:g} °C")
    ax.set_xlabel("Drive current (mA)")
    ax.set_ylabel("Optical power (mW)")
    ax.legend(fontsize=8)
    ax.set_title("L–I at each temperature")
    T = np.array(temps, float)
    ith = np.array([c[2].threshold_fit_mA for c in curves])
    ax2.plot(T, ith, "o", color="#1f4e8c")
    if t0 and np.isfinite(t0):
        xs = np.linspace(T.min(), T.max(), 50)
        a = np.polyfit(T, np.log(ith), 1)
        ax2.plot(xs, np.exp(np.polyval(a, xs)), "-", color="#d1495b", label=f"$T_0$ = {t0:.0f} K")
        ax2.legend(fontsize=8)
    ax2.set_xlabel("TEC temperature (°C)")
    ax2.set_ylabel("Threshold current (mA)")
    ax2.set_title("Threshold vs temperature")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_stability(df, path, title):
    fig, ax = plt.subplots(figsize=(8, 3.5))
    t = df["elapsed_s"] / 60.0
    p = df["power_mW"]
    ax.plot(t, p, lw=0.8, color="#1f4e8c")
    mean = p.mean()
    ax.axhline(mean, color="#888", ls=":", lw=1)
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("Power (mW)")
    ax.set_title(f"{title} — mean {mean:.3f} mW, std {p.std() / mean * 100:.2f} %, "
                 f"peak-to-peak {(p.max() - p.min()) / mean * 100:.2f} %")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_tuning(df, path):
    fig, ax = plt.subplots(figsize=(7, 4))
    for T, g in df.groupby("temperature_C"):
        g = g.sort_values("current_mA")
        ax.plot(g["current_mA"], g["wavelength_nm"], "o-", ms=3, lw=1, label=f"{T:g} °C")
    ax.set_xlabel("Drive current (mA)")
    ax.set_ylabel("Peak wavelength (nm)")
    ax.legend(fontsize=8)
    ax.set_title("Wavelength tuning")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
