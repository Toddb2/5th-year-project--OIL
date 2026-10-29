"""The experiment runner and its helpers, all in simulation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from oil852.instruments.tec import SimTEC, TECError
from oil852.instruments.voa import VOAError, voltage_for_dB
from oil852.thermistor import resistance_kohm, temperature_C

ROOT = Path(__file__).resolve().parents[1]


def test_thermistor_round_trip():
    assert resistance_kohm(25.0) == pytest.approx(10.0)
    for T in (15.0, 20.0, 30.0, 35.0):
        assert temperature_C(resistance_kohm(T)) == pytest.approx(T, abs=1e-9)
    assert resistance_kohm(20.0) > 10.0 > resistance_kohm(30.0)  # NTC


def test_sim_tec_settles_and_refuses_out_of_range():
    tec = SimTEC(tau_s=0.05, min_C=15, max_C=35)
    tec.connect()
    assert tec.go_to(20.0, tol_C=0.05, hold_s=0.1) == pytest.approx(20.0, abs=0.05)
    with pytest.raises(TECError):
        tec.set_C(10.0)


def test_runaway_disables_tec():
    class Backwards(SimTEC):
        def read_C(self):  # heats when asked to cool
            self._advance()
            return 2 * 25.0 - self._T
    tec = Backwards(tau_s=0.05)
    with pytest.raises(TECError, match="running away"):
        tec.go_to(20.0, hold_s=0.1, timeout_s=5)
    assert not tec.is_enabled()


def test_voa_lookup(tmp_path):
    f = tmp_path / "lookup.json"
    f.write_text(json.dumps({"curve": {"control_V": [0, 1, 2, 3, 4], "attenuation_dB": [0, 1, 10, 30, 40]}}))
    assert voltage_for_dB(f, 20) == pytest.approx(2.5)
    with pytest.raises(VOAError):
        voltage_for_dB(f, 45)


def test_small_campaign_runs_end_to_end(tmp_path):
    camp = tmp_path / "campaign.toml"
    camp.write_text("""
[campaign]
name = "test"
stages = ["characterisation", "locking", "pulsed", "qkd"]
mode = "sim"
[characterisation]
temperatures_C = [20.0, 30.0]
stop_mA = 120.0
stability = false
tuning = false
[locking]
voa_attenuations_dB = [20.0]
master_currents = "130:150:2"
spectra = false
[pulsed]
scope_shots = 2
slave_bias_mA = [300.0]
[qkd]
protocols = ["dps"]
spools_km = [1.0]
""")
    env = dict(os.environ, OIL852_DATA_ROOT=str(tmp_path), OIL852_NO_GIT="1", MPLBACKEND="Agg")
    r = subprocess.run([sys.executable, str(ROOT / "run_experiment.py"), "--campaign", str(camp)],
                       env=env, cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    folder = next((tmp_path / "campaigns").iterdir())
    state = json.loads((folder / "state.json").read_text())
    assert all(rec["status"] == "ok" for rec in state["done"].values()), state["done"]
    summary = json.loads((folder / "summary.json").read_text())
    assert len(summary["liv"]) == 2 and summary["T0_K"] > 0
    assert summary["locking_maps"][0]["windows_mA"]
    assert summary["qber_dps"]["dps_qber_pct"] < 11
    assert (folder / "report.html").exists()

    # resuming a finished campaign does nothing but rebuild nothing new
    r2 = subprocess.run([sys.executable, str(ROOT / "run_experiment.py"), "--resume", str(folder)],
                        env=env, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0 and "already ok" in r2.stdout
