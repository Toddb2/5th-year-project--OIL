"""Check the analysis recovers known parameters from the simulated laser."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oil852.analysis import analyse_li, characteristic_temperature, tuning_coefficients  # noqa: E402
from oil852.instruments.sim import SimLaser  # noqa: E402


def sim_curve(T=25.0, stop=230, step=2):
    laser = SimLaser(noise=0.002)
    laser.temperature_C = T
    I = np.arange(0, stop + step, step, dtype=float)
    return pd.DataFrame({"current_mA": I, "power_mW": [laser.power_W(i) * 1000 for i in I],
                         "voltage_V": [laser.voltage_V(i) for i in I]}), laser


def test_threshold_and_slope():
    df, laser = sim_curve()
    r = analyse_li(df)
    assert abs(r.threshold_fit_mA - 50) < 3
    assert abs(r.threshold_d2_mA - 50) < 6
    assert abs(r.slope_W_per_A - 0.09) < 0.005
    assert r.fit_r2 > 0.99


def test_series_resistance():
    df, laser = sim_curve()
    r = analyse_li(df)
    # the diode term adds a little to the apparent slope, so allow some margin
    assert 3.5 < r.series_resistance_ohm < 5.5


def test_t0():
    ths = [analyse_li(sim_curve(T)[0]).threshold_fit_mA for T in (20, 25, 30, 35)]
    t0 = characteristic_temperature([20, 25, 30, 35], ths)
    assert 80 < t0 < 170


def test_tuning_and_mode_hop():
    rows = []
    for T in (20, 25):
        for I in range(60, 201, 10):
            lam = 852 + 0.002 * (I - 100) + 0.06 * (T - 25) + (0.1 if I >= 150 else 0)  # 0.1 nm hop at 150 mA
            rows.append({"temperature_C": T, "current_mA": I, "wavelength_nm": lam})
    res = tuning_coefficients(pd.DataFrame(rows))
    assert abs(res["per_temperature"][100.0] - 0.06) < 1e-6
    assert any(h["between_mA"] == [140.0, 150.0] for h in res["mode_hops"])
