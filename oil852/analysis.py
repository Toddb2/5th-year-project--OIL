"""Extract laser parameters from measured data.

L-I-V:   threshold current (two methods), slope efficiency, series resistance,
         turn-on voltage, wall-plug efficiency, monitor-photodiode responsivity.
Several temperatures: characteristic temperature T0 from I_th(T) = I_0 exp(T/T0).
Tuning:  wavelength shift per mA and per degree C, and mode-hop detection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


@dataclass
class LIResult:
    threshold_fit_mA: float          # linear fit above threshold, extrapolated to P = 0
    threshold_d2_mA: float           # peak of d2P/dI2
    slope_W_per_A: float             # slope efficiency above threshold
    fit_r2: float
    fit_range_mA: tuple[float, float]
    max_power_mW: float
    current_at_max_mA: float
    series_resistance_ohm: float | None
    turn_on_voltage_V: float | None
    max_wallplug_eff_pct: float | None
    pd_responsivity_mA_per_mW: float | None

    def as_dict(self):
        d = asdict(self)
        d["fit_range_mA"] = list(self.fit_range_mA)
        return d


def load_li(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.dropna(subset=["current_mA", "power_mW"]).sort_values("current_mA")
    return df.reset_index(drop=True)


def _uniform(I, P, step=None):
    step = step or max(np.median(np.diff(I)), 0.5)
    grid = np.arange(I.min(), I.max() + step / 2, step)
    return grid, np.interp(grid, I, P)


def threshold_second_derivative(I, P) -> float:
    """Current where d2P/dI2 peaks: the kink of the L-I curve."""
    grid, Pg = _uniform(np.asarray(I, float), np.asarray(P, float))
    if len(grid) < 7:
        return float("nan")
    win = min(len(grid) // 2 * 2 - 1, max(5, (len(grid) // 10) * 2 + 1))
    d2 = savgol_filter(Pg, window_length=win, polyorder=2, deriv=2)
    return float(grid[int(np.argmax(d2))])


def threshold_linear(I, P, guess_mA: float | None = None, min_points: int = 4):
    """Fit P = eta (I - I_th) to the lasing part of the curve and extrapolate to P = 0.

    The fit window starts a little above the kink (to avoid its rounding) and stops before
    any roll-over at the top, so it uses the straight part of the curve only."""
    I = np.asarray(I, float)
    P = np.asarray(P, float)
    if guess_mA is None or not np.isfinite(guess_mA):
        guess_mA = threshold_second_derivative(I, P)
    lo = guess_mA + max(5.0, 0.15 * guess_mA)
    # stop before roll-over: where the local slope drops below 70 % of the median lasing slope
    above = I > lo
    hi = I.max()
    if above.sum() >= min_points + 2:
        s = np.gradient(P[above], I[above])
        med = np.median(s)
        bad = np.where(s < 0.7 * med)[0]
        bad = bad[bad > len(s) // 2]
        if len(bad):
            hi = I[above][bad[0]]
    sel = (I >= lo) & (I <= hi)
    if sel.sum() < min_points:
        sel = I > guess_mA
    if sel.sum() < 2:
        raise ValueError("Not enough points above threshold to fit. Extend the sweep.")
    eta, c = np.polyfit(I[sel], P[sel], 1)
    pred = eta * I[sel] + c
    ss_res = np.sum((P[sel] - pred) ** 2)
    ss_tot = np.sum((P[sel] - P[sel].mean()) ** 2) or 1.0
    return float(-c / eta), float(eta), float(1 - ss_res / ss_tot), (float(I[sel].min()), float(I[sel].max()))


def analyse_li(df: pd.DataFrame) -> LIResult:
    I = df["current_mA"].to_numpy(float)
    P = df["power_mW"].to_numpy(float)
    ith_d2 = threshold_second_derivative(I, P)
    ith_fit, eta_mW_per_mA, r2, rng = threshold_linear(I, P, ith_d2)

    rs = v_on = wpe = resp = None
    if "voltage_V" in df and df["voltage_V"].notna().sum() >= 4:
        dv = df.dropna(subset=["voltage_V"])
        Iv, V = dv["current_mA"].to_numpy(float), dv["voltage_V"].to_numpy(float)
        hi = Iv > max(ith_fit, 0.3 * Iv.max())
        if hi.sum() >= 3:
            slope, icpt = np.polyfit(Iv[hi] / 1000.0, V[hi], 1)
            rs, v_on = float(slope), float(icpt)
        lasing = (Iv > ith_fit) & (V > 0)
        if lasing.any():
            Pv = np.interp(Iv[lasing], I, P)
            wpe = float(np.max(Pv / (Iv[lasing] * V[lasing])) * 100.0)  # mW / (mA V) = fraction
    if "pd_mA" in df and df["pd_mA"].notna().sum() >= 4:
        dp = df.dropna(subset=["pd_mA"])
        sel = dp["current_mA"] > ith_fit
        if sel.sum() >= 3:
            resp = float(np.polyfit(dp.loc[sel, "power_mW"], dp.loc[sel, "pd_mA"], 1)[0])

    k = int(np.argmax(P))
    return LIResult(threshold_fit_mA=ith_fit, threshold_d2_mA=ith_d2, slope_W_per_A=eta_mW_per_mA,
                    fit_r2=r2, fit_range_mA=rng, max_power_mW=float(P[k]), current_at_max_mA=float(I[k]),
                    series_resistance_ohm=rs, turn_on_voltage_V=v_on, max_wallplug_eff_pct=wpe,
                    pd_responsivity_mA_per_mW=resp)


def characteristic_temperature(temps_C, thresholds_mA):
    """T0 from ln(I_th) = ln(I_0) + T/T0. Needs two or more temperatures."""
    T = np.asarray(temps_C, float)
    ith = np.asarray(thresholds_mA, float)
    if len(T) < 2:
        return None
    slope, _ = np.polyfit(T, np.log(ith), 1)
    return float(1.0 / slope) if slope > 0 else float("inf")


def tuning_coefficients(df: pd.DataFrame, hop_factor: float = 3.0) -> dict:
    """Fit wavelength against current (per temperature) and against temperature (per current).
    Flags mode hops: steps much bigger than the typical step between neighbouring points."""
    out = {"per_current": {}, "per_temperature": {}, "mode_hops": []}
    for T, g in df.groupby("temperature_C"):
        g = g.sort_values("current_mA")
        if len(g) >= 2:
            out["per_current"][float(T)] = float(np.polyfit(g["current_mA"], g["wavelength_nm"], 1)[0])
        if len(g) >= 3:
            steps = np.abs(np.diff(g["wavelength_nm"].to_numpy()))
            med = np.median(steps) or 1e-9
            for j in np.where(steps > hop_factor * med)[0]:
                out["mode_hops"].append({"temperature_C": float(T),
                                         "between_mA": [float(g["current_mA"].iloc[j]), float(g["current_mA"].iloc[j + 1])],
                                         "jump_nm": float(steps[j])})
    for I, g in df.groupby("current_mA"):
        if g["temperature_C"].nunique() >= 2:
            out["per_temperature"][float(I)] = float(np.polyfit(g["temperature_C"], g["wavelength_nm"], 1)[0])
    return out
