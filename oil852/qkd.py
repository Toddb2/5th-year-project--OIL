"""QKD link models for the OIL transmitter: channel transmittance, detection rates, QBER,
and the asymptotic decoy-state BB84 key rate.

Decoy-state BB84 (infinite decoys, Lo, Ma and Chen, PRL 94, 230504 (2005); GLLP formula):
    R = q { -Q_mu f H2(E_mu) + Q_1 [1 - H2(e_1)] }
    Q_mu   = Y0 + 1 - exp(-eta mu)
    E_mu   = [e0 Y0 + e_d (1 - exp(-eta mu))] / Q_mu
    Y1     = Y0 + eta,   Q_1 = Y1 mu exp(-mu),   e_1 = (e0 Y0 + e_d eta) / Y1
with e0 = 1/2, q = 1/2 for standard BB84 sifting, f the error-correction inefficiency.

COW and DPS have their own security analyses (e.g. Stucki et al., APL 87, 194108 (2005) for COW;
Inoue et al., PRA 68, 022317 (2003) for DPS). Only their detection rates and QBER are modelled here;
use the decoy-BB84 rate as the benchmark.
"""

from __future__ import annotations

import numpy as np


def h2(x):
    x = np.clip(np.asarray(x, float), 1e-15, 1 - 1e-15)
    return -x * np.log2(x) - (1 - x) * np.log2(1 - x)


def channel_transmittance(length_km, attenuation_dB_per_km=3.5, fixed_loss_dB=0.0, bob_loss_dB=0.0):
    """Fibre (or free-space) transmittance excluding the detector efficiency."""
    loss = np.asarray(length_km, float) * attenuation_dB_per_km + fixed_loss_dB + bob_loss_dB
    return 10 ** (-loss / 10)


def dark_count_prob(dark_Hz: float, gate_ns: float) -> float:
    """Probability of a dark count within one detection window."""
    return 1 - np.exp(-dark_Hz * gate_ns * 1e-9)


def bb84_decoy_rate(mu, eta, Y0, e_d=0.01, f_ec=1.16, q=0.5):
    """Secure key per sent pulse (bits/pulse), asymptotic decoy BB84. eta includes the detector."""
    mu = np.asarray(mu, float)
    eta = np.asarray(eta, float)
    Q_mu = Y0 + 1 - np.exp(-eta * mu)
    E_mu = (0.5 * Y0 + e_d * (1 - np.exp(-eta * mu))) / Q_mu
    Y1 = Y0 + eta
    Q1 = Y1 * mu * np.exp(-mu)
    e1 = (0.5 * Y0 + e_d * eta) / Y1
    R = q * (-Q_mu * f_ec * h2(E_mu) + Q1 * (1 - h2(e1)))
    return np.maximum(R, 0.0)


def optimal_mu(eta, Y0, e_d=0.01, f_ec=1.16):
    mus = np.linspace(0.01, 1.2, 600)
    r = bb84_decoy_rate(mus, eta, Y0, e_d, f_ec)
    return float(mus[np.argmax(r)]), float(r.max())


def detection_prob(mu, eta, Y0):
    """Probability that a pulse with mean photon number mu gives a click."""
    return Y0 + 1 - np.exp(-np.asarray(eta) * mu)


def qber_from_visibility(V):
    """Interferometric QBER (DPS phase errors, COW monitoring line) from fringe visibility."""
    return (1 - np.asarray(V, float)) / 2


def qber_with_darks(signal_error: float, signal_prob, Y0):
    """Overall QBER when dark counts (50 % error) add to signal clicks with error probability e_d."""
    signal_prob = np.asarray(signal_prob, float)
    return (signal_error * signal_prob + 0.5 * Y0) / (signal_prob + Y0)


def dead_time_limited_rate(rate_Hz, dead_time_ns):
    """Measured count rate for a non-paralysable detector."""
    r = np.asarray(rate_Hz, float)
    return r / (1 + r * dead_time_ns * 1e-9)
