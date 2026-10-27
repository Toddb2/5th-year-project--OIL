"""Optical injection locking: unit conversions and the textbook locking range.

Sign convention: detuning = master frequency - free-running slave frequency.
For a slave with linewidth enhancement factor alpha and coupling coefficient kappa,
a locked solution exists for

    -kappa * sqrt(rho) * sqrt(1 + alpha^2)  <=  detuning (rad/s)  <=  kappa * sqrt(rho)

where rho = P_injected / P_slave (Mogensen, Olesen and Jacobsen, IEEE JQE 21, 784 (1985);
Lau, Wong and Wu, IEEE JSTQE 15, 618 (2009)). The dynamically stable part is narrower,
especially at the positive-detuning edge and at weak injection, so treat these as outer limits.

kappa ~ (1 / tau_in) * (1 - R) / sqrt(R), with tau_in = 2 n_g L / c the cavity round-trip time.
"""

from __future__ import annotations

import numpy as np

C = 299_792_458.0


def ghz_per_pm(wavelength_nm: float = 852.0) -> float:
    """Frequency change for a 1 pm wavelength change (about 0.41 GHz/pm at 852 nm)."""
    lam = wavelength_nm * 1e-9
    return C * 1e-12 / lam**2 / 1e9


def detuning_ghz(master_nm, slave_nm):
    """Master minus slave optical frequency in GHz."""
    return C / (np.asarray(master_nm) * 1e-9) / 1e9 - C / (np.asarray(slave_nm) * 1e-9) / 1e9


def coupling_coefficient(length_mm: float = 1.0, group_index: float = 3.6, facet_R: float = 0.3) -> float:
    """Injection coupling coefficient kappa in 1/s (order-of-magnitude estimate)."""
    tau_in = 2 * group_index * length_mm * 1e-3 / C
    return (1 / tau_in) * (1 - facet_R) / np.sqrt(facet_R)


def locking_range_ghz(rho_dB, kappa_per_s: float, alpha: float):
    """(lower, upper) edges of the locking range in GHz for injection ratio rho_dB."""
    rho = 10 ** (np.asarray(rho_dB, float) / 10)
    upper = kappa_per_s * np.sqrt(rho) / (2 * np.pi) / 1e9
    lower = -kappa_per_s * np.sqrt(rho) * np.sqrt(1 + alpha**2) / (2 * np.pi) / 1e9
    return lower, upper


def master_current_window_mA(rho_dB, kappa_per_s, alpha, tuning_pm_per_mA=2.0, wavelength_nm=852.0):
    """Width of the locking range expressed as master drive current (mA)."""
    lo, hi = locking_range_ghz(rho_dB, kappa_per_s, alpha)
    ghz_per_mA = tuning_pm_per_mA * ghz_per_pm(wavelength_nm)
    return (hi - lo) / ghz_per_mA


def locked_windows(currents_mA, locked):
    """Contiguous locked stretches of a master-current sweep: list of (start, end) in mA."""
    I = np.asarray(currents_mA, float)
    L = np.asarray(locked, bool)
    order = np.argsort(I)
    I, L = I[order], L[order]
    windows, start, prev = [], None, None
    for i, flag in zip(I, L):
        if flag and start is None:
            start = i
        if not flag and start is not None:
            windows.append((start, prev))
            start = None
        prev = i
    if start is not None:
        windows.append((start, I[-1]))
    return windows
