"""Optical spectra exported from the OSA (or a CCS spectrometer): peaks, side-mode
suppression ratio (SMSR), FP mode spacing, and a simple locked / not-locked test."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks


@dataclass
class SpectrumResult:
    peak_nm: float
    peak_dBm: float
    smsr_dB: float | None
    side_mode_nm: float | None
    mode_spacing_nm: float | None
    n_modes_within_20dB: int

    def as_dict(self):
        return asdict(self)


def load_spectrum(path, power_unit: str = "auto"):
    """Read a two-column wavelength/power export. Header lines, commas, semicolons or tabs are fine.
    Wavelengths in m or um are converted to nm. Power is returned in dBm: linear (mW or W)
    columns are converted when power_unit is 'mW' or 'W', or detected automatically."""
    text = Path(path).read_text(errors="ignore")
    rows = []
    for line in text.splitlines():
        parts = [p for p in re.split(r"[,;\t ]+", line.strip()) if p]
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(rows) < 5:
        raise ValueError(f"{path}: could not find two numeric columns")
    wl, p = np.array(rows).T
    if wl.max() < 1e-3:      # metres
        wl = wl * 1e9
    elif wl.max() < 10:      # micrometres
        wl = wl * 1e3
    unit = power_unit
    if unit == "auto":
        unit = "dBm" if p.min() < 0 else "mW"
    if unit == "mW":
        p = 10 * np.log10(np.clip(p, 1e-12, None))
    elif unit == "W":
        p = 10 * np.log10(np.clip(p * 1e3, 1e-15, None))
    order = np.argsort(wl)
    return wl[order], p[order]


def analyse_spectrum(wl_nm, p_dBm, min_separation_nm: float = 0.02, prominence_dB: float = 3.0) -> SpectrumResult:
    wl_nm = np.asarray(wl_nm, float)
    p = np.asarray(p_dBm, float)
    step = np.median(np.diff(wl_nm))
    dist = max(1, int(round(min_separation_nm / step)))
    idx, _ = find_peaks(p, distance=dist, prominence=prominence_dB)
    if len(idx) == 0:
        idx = np.array([int(np.argmax(p))])
    main = idx[np.argmax(p[idx])]
    others = idx[idx != main]
    smsr = side_nm = None
    if len(others):
        k = others[np.argmax(p[others])]
        smsr = float(p[main] - p[k])
        side_nm = float(wl_nm[k])
    strong = np.sort(wl_nm[idx[p[idx] > p[main] - 20]])
    spacing = float(np.median(np.diff(strong))) if len(strong) >= 3 else None
    return SpectrumResult(peak_nm=float(wl_nm[main]), peak_dBm=float(p[main]), smsr_dB=smsr,
                          side_mode_nm=side_nm, mode_spacing_nm=spacing, n_modes_within_20dB=int(len(strong)))


def looks_locked(res: SpectrumResult, master_nm: float | None = None, smsr_min_dB: float = 30.0,
                 tolerance_nm: float = 0.01) -> bool:
    """Single dominant line, and (if given) sitting on the master wavelength."""
    single = res.smsr_dB is None or res.smsr_dB >= smsr_min_dB
    on_master = master_nm is None or abs(res.peak_nm - master_nm) <= tolerance_nm
    return bool(single and on_master)


def synthetic_fp(locked: bool, centre_nm=852.0, spacing_nm=0.1, n=9, master_nm=None, seed=0):
    """Fake OSA trace for tests: an FP comb, or one dominant line when locked."""
    rng = np.random.default_rng(seed)
    wl = np.linspace(centre_nm - 0.6, centre_nm + 0.6, 2401)
    p = np.full_like(wl, -70.0) + rng.normal(0, 0.5, wl.size)
    lines = [(centre_nm + (k - n // 2) * spacing_nm, -8 - 1.5 * abs(k - n // 2)) for k in range(n)]
    if locked:
        m = master_nm or centre_nm
        lines = [(m, 2.0)] + [(c, h - 40) for c, h in lines if abs(c - m) > 1e-6]
    for c, h in lines:
        p = np.maximum(p, h - ((wl - c) / 0.004) ** 2 * 3)
    return wl, p


def to_csv_text(wl, p) -> str:
    buf = io.StringIO()
    buf.write("wavelength_nm,power_dBm\n")
    for a, b in zip(wl, p):
        buf.write(f"{a:.5f},{b:.3f}\n")
    return buf.getvalue()
