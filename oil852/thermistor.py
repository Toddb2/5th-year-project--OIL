"""Thermistor resistance <-> temperature (beta model).

The TTC001 regulates a thermistor to a resistance set point in kOhm, so temperatures have to be
converted. The beta model is accurate to roughly 0.1-0.2 C over 15-35 C, which is plenty for
labelling runs and stepping the temperature. Put the laser's own R25 and beta in
config/bench.toml [tec] (check the laser datasheet; 10 kOhm and ~3900-3990 K are typical).
"""

from __future__ import annotations

import math

T25_K = 298.15


def resistance_kohm(temp_C: float, r25_kohm: float = 10.0, beta_K: float = 3950.0) -> float:
    T = temp_C + 273.15
    return r25_kohm * math.exp(beta_K * (1.0 / T - 1.0 / T25_K))


def temperature_C(r_kohm: float, r25_kohm: float = 10.0, beta_K: float = 3950.0) -> float:
    if r_kohm <= 0:
        raise ValueError(f"thermistor resistance must be positive, got {r_kohm}")
    inv_T = 1.0 / T25_K + math.log(r_kohm / r25_kohm) / beta_K
    return 1.0 / inv_T - 273.15
