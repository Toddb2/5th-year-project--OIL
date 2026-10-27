"""Checks for the injection-locking, pulse, pattern and QKD modules."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oil852.instruments.tek_scope import synthetic_pulses  # noqa: E402
from oil852.locking import ghz_per_pm, locked_windows, locking_range_ghz  # noqa: E402
from oil852.patterns import cow_slots, master_waveform, slave_waveform  # noqa: E402
from oil852.pulses import analyse_pulses  # noqa: E402
from oil852.qkd import bb84_decoy_rate, channel_transmittance, h2, qber_from_visibility  # noqa: E402
from oil852.spectrum import analyse_spectrum, looks_locked, synthetic_fp  # noqa: E402


def test_ghz_per_pm_at_852():
    assert abs(ghz_per_pm(852.0) - 0.413) < 0.002


def test_locking_range_shape():
    lo, hi = locking_range_ghz(-20, 5e10, 3.0)
    assert hi > 0 > lo
    assert abs(lo / hi + np.sqrt(10)) < 1e-9  # asymmetry factor sqrt(1 + alpha^2)


def test_locked_windows():
    I = np.arange(0, 10)
    L = [0, 1, 1, 0, 0, 1, 1, 1, 0, 1]
    assert locked_windows(I, L) == [(1, 2), (5, 7), (9, 9)]


def test_spectrum_locked_vs_free():
    free = analyse_spectrum(*synthetic_fp(False))
    locked = analyse_spectrum(*synthetic_fp(True, master_nm=852.0))
    assert not looks_locked(free)
    assert looks_locked(locked, master_nm=852.0)
    assert abs(free.mode_spacing_nm - 0.1) < 0.005


def test_pulse_analysis_recovers_period_and_width():
    t, v = synthetic_pulses(period_ns=50, width_ns=0.3, jitter_ps=8, n_pulses=40)
    r = analyse_pulses(t, v)
    assert abs(r.period_ns - 50) < 0.01
    assert abs(r.fwhm_ps - 300) < 20
    assert r.timing_jitter_ps < 20


def test_cow_slots():
    slots, labels = cow_slots([0, 1, 0], decoy_fraction=0.0)
    assert list(slots) == [1, 0, 0, 1, 1, 0]


def test_waveform_lengths():
    assert len(slave_waveform([1, 0, 1, 1], 200)) == 800
    assert len(master_waveform([0, 1, 0, 1], 200)) == 800


def test_decoy_rate_behaviour():
    assert abs(h2(0.5) - 1) < 1e-9
    assert abs(qber_from_visibility(0.9) - 0.05) < 1e-12
    eta_short = channel_transmittance(1, 3.5) * 0.5
    eta_long = channel_transmittance(30, 3.5) * 0.5
    r_short = bb84_decoy_rate(0.5, eta_short, 1e-7)
    r_long = bb84_decoy_rate(0.5, eta_long, 1e-7)
    assert r_short > 1e-3
    assert r_long == 0


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "04_qkd" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_timetag_dps_qber(tmp_path):
    tt = _load("timetag_qber")
    tags = tt.synth("dps", tmp_path, visibility=0.9, seconds=0.05)

    class A:
        mon_c, mon_d, offset_ps, window_ps = 2, 3, None, 1000.0

    import json
    meta = json.loads((tmp_path / "meta.json").read_text())
    sent = pd.read_csv(tmp_path / "sent.csv", dtype={"symbol": str})
    res = tt.dps_analysis(pd.read_csv(tags), sent, meta, A)
    assert abs(res["dps_qber_pct"] - 5.0) < 1.0
