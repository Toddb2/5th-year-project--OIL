"""Pulse-train analysis for gain-switched slave pulses captured on the scope."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class PulseResult:
    n_pulses: int
    period_ns: float
    fwhm_ps: float
    fwhm_std_ps: float
    timing_jitter_ps: float
    amplitude_V: float
    amplitude_cv_pct: float
    extinction_dB: float | None

    def as_dict(self):
        return asdict(self)


def _fwhm(t, v, i):
    half = v[i] / 2
    l = i
    while l > 0 and v[l] > half:
        l -= 1
    r = i
    while r < len(v) - 1 and v[r] > half:
        r += 1
    # linear interpolation at both crossings
    tl = np.interp(half, [v[l], v[l + 1]], [t[l], t[l + 1]])
    tr = np.interp(half, [v[r], v[r - 1]], [t[r], t[r - 1]])
    return tr - tl


def analyse_pulses(t_s, v, min_height_frac=0.3, baseline_V=None) -> PulseResult:
    t = np.asarray(t_s, float)
    v = np.asarray(v, float)
    base = np.median(v) if baseline_V is None else baseline_V
    v = v - base
    dt = t[1] - t[0]
    idx, _ = find_peaks(v, height=min_height_frac * v.max(), distance=max(1, int(1e-9 / dt)))
    if len(idx) < 3:
        raise ValueError("Fewer than 3 pulses found; check the capture and trigger")
    # sub-sample peak times: centroid over the part of each pulse above half maximum
    tp = []
    for i in idx:
        half = v[i] / 2
        l, r = i, i
        while l > 0 and v[l - 1] > half:
            l -= 1
        while r < len(v) - 1 and v[r + 1] > half:
            r += 1
        seg = slice(l, r + 1)
        tp.append(np.sum(t[seg] * v[seg]) / np.sum(v[seg]))
    tp = np.array(tp)
    period = np.median(np.diff(tp))
    k = np.round((tp - tp[0]) / period)
    fit = np.polyfit(k, tp, 1)
    jitter = np.std(tp - np.polyval(fit, k))
    widths = np.array([_fwhm(t, v, i) for i in idx])
    amps = v[idx]
    # extinction: mean peak vs mean level halfway between pulses
    mids = []
    for a, b in zip(tp[:-1], tp[1:]):
        m = int(np.argmin(np.abs(t - (a + b) / 2)))
        mids.append(v[m])
    floor = np.mean(np.abs(mids)) if mids else 0
    ext = 10 * np.log10(np.mean(amps) / floor) if floor > 0 else None
    return PulseResult(n_pulses=len(idx), period_ns=period * 1e9, fwhm_ps=float(np.mean(widths) * 1e12),
                       fwhm_std_ps=float(np.std(widths) * 1e12), timing_jitter_ps=float(jitter * 1e12),
                       amplitude_V=float(np.mean(amps)), amplitude_cv_pct=float(np.std(amps) / np.mean(amps) * 100),
                       extinction_dB=ext)
