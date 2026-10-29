"""The experiment runner behind run_experiment.py.

A campaign is an ordered list of steps across the four stages. Each measurement step runs one of
the stage scripts as a subprocess (so a crash in one never takes the others down), with
OIL852_DATA_ROOT pointing at the campaign folder and OIL852_RUN_LOG collecting the run folders it
makes. Between steps the runner sets the laser temperature (TTC001) and the VOA, and stops to ask
you whenever something has to be done by hand (move a fibre, set the slave driver, export an OSA
trace). Progress is saved after every step in state.json, so a stopped campaign can be resumed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .cli import PREFLIGHT
from .config import REPO_ROOT

STAGES = ["characterisation", "locking", "pulsed", "qkd"]


class Abort(Exception):
    """Operator asked to quit."""


class SkipStep(Exception):
    """Operator chose to skip the current step."""


class StepFailed(Exception):
    pass


@dataclass
class Step:
    id: str
    stage: str
    title: str
    fn: Callable[["Campaign"], dict | None]
    needs_bench: bool = False  # skipped in sim mode


@dataclass
class Campaign:
    camp: dict
    bench_cfg: dict
    folder: Path
    mode: str
    tec_control: str
    on_error: str
    bench_config_path: str | None = None
    state: dict = field(default_factory=lambda: {"done": {}, "values": {}})
    _tec: object = None
    _tec_at: float | None = None
    _voa: object = None
    _awg_running: bool = False

    # ---- paths and state ----------------------------------------------------------
    @property
    def data(self) -> Path:
        return self.folder / "data"

    @property
    def sim(self) -> bool:
        return self.mode == "sim"

    def save_state(self):
        (self.folder / "state.json").write_text(json.dumps(self.state, indent=2, default=str))

    def runs(self, step_prefix: str) -> list[Path]:
        out = []
        for sid, rec in self.state["done"].items():
            if sid.startswith(step_prefix) and rec.get("status") == "ok":
                out += [Path(r) for r in rec.get("runs", [])]
        return out

    def value(self, key, default=None):
        return self.state["values"].get(key, default)

    def set_value(self, key, v):
        self.state["values"][key] = v
        self.save_state()

    def log(self, msg: str):
        print(msg)
        with open(self.folder / "log.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S} {msg}\n")

    # ---- talking to the operator --------------------------------------------------
    def prompt(self, msg: str):
        """Something to do by hand. Enter = done, s = skip this step, q = quit."""
        if self.sim:
            self.log(f"  [sim] would ask: {msg}")
            return
        print()
        ans = input(f">> {msg}\n   [Enter = done, s = skip this step, q = quit]: ").strip().lower()
        if ans == "q":
            raise Abort()
        if ans == "s":
            raise SkipStep()

    def ask_path(self, msg: str) -> Path | None:
        """Ask for a file. Enter = none."""
        while True:
            ans = input(f">> {msg}\n   [path, Enter = none, q = quit]: ").strip().strip('"')
            if ans.lower() == "q":
                raise Abort()
            if not ans:
                return None
            p = Path(ans).expanduser()
            if p.exists():
                return p
            print(f"   {p} not found.")

    # ---- running stage scripts ----------------------------------------------------
    def script(self, rel: str, *args) -> list[Path]:
        """Run a stage script; return the run folders it reported."""
        runlog = self.folder / ".runlog"
        runlog.write_text("")
        env = dict(os.environ, OIL852_DATA_ROOT=str(self.data), OIL852_RUN_LOG=str(runlog),
                   PYTHONIOENCODING="utf-8", MPLBACKEND="Agg")
        cmd = [sys.executable, str(REPO_ROOT / rel), *[str(x) for x in args]]
        if self.bench_config_path:
            cmd += ["--config", self.bench_config_path]
        self.log(f"  $ python {rel} {' '.join(str(x) for x in args)}")
        r = subprocess.run(cmd, env=env, cwd=REPO_ROOT)
        runs = [Path(x) for x in runlog.read_text(encoding="utf-8").splitlines() if x.strip()]
        if r.returncode != 0:
            raise StepFailed(f"{rel} exited with code {r.returncode}")
        return list(dict.fromkeys(runs))

    def mode_for(self, script: str) -> str:
        """Each stage script supports a slightly different set of modes."""
        m = self.mode
        if m == "sim":
            return "sim"
        if script in ("li_sweep", "wavelength_log", "power_stability"):
            return m
        if script == "voa_calibration":
            return "manual" if m == "manual" else "auto"
        if script == "locking_map":
            return "auto" if m == "auto" else "manual"
        if script == "scope_capture":
            return "auto"
        return m

    # ---- temperature -------------------------------------------------------------
    def set_temp(self, temp_C: float):
        tcfg = self.bench_cfg.get("tec", {})
        if self._tec is None:
            from .instruments.tec import open_tec
            self._tec = open_tec(self.bench_cfg, "sim" if self.sim else self.tec_control)
            self._tec.connect()
        if self._tec_at is not None and abs(self._tec_at - temp_C) < 1e-6:
            return
        self.log(f"  TEC -> {self._tec.describe(temp_C)}")
        T = self._tec.go_to(temp_C, float(tcfg.get("tolerance_C", 0.05)), float(tcfg.get("hold_s", 30)),
                            float(tcfg.get("timeout_s", 600)))
        self._tec_at = temp_C
        self.log(f"  TEC holding {T:.3f} C")

    # ---- VOA ---------------------------------------------------------------------
    def voa_control(self) -> str:
        if self.sim:
            return "sim"
        return self.bench_cfg.get("voa", {}).get("control", "manual")

    def set_voa_dB(self, dB: float) -> float:
        from .instruments.voa import open_voa, voltage_for_dB
        lookup = self.value("voa_lookup")
        if not lookup:
            raise StepFailed("No VOA calibration yet (step l.voa). Run it first or resume from it.")
        v = voltage_for_dB(lookup, dB)
        if self._voa is None:
            self._voa = open_voa(self.bench_cfg, self.voa_control())
        self.log(f"  VOA -> {dB:g} dB attenuation ({v:.3f} V)")
        self._voa.set_V(v)
        self.set_value("voa_dB_now", dB)
        return v

    def reapply_voa(self):
        """The AWG pulse scripts reset the AWG, which clears a VOA channel driven from it."""
        dB = self.value("voa_dB_now")
        if dB is not None and self.voa_control() == "awg":
            self.set_voa_dB(dB)

    # ---- AWG --------------------------------------------------------------------
    def awg(self, *args):
        if self.sim:
            self.log(f"  [sim] AWG: {' '.join(args)}")
            return
        self.script("03_pulsed/awg_oil_patterns.py", *args)
        self._awg_running = args[0] != "off"
        if self._awg_running:
            self.reapply_voa()

    # ---- the loop ---------------------------------------------------------------
    def run(self, steps: list[Step]):
        for st in steps:
            if st.id in self.state["done"]:
                self.log(f"[{st.id}] already {self.state['done'][st.id]['status']} - skipping")
                continue
            if st.needs_bench and self.sim:
                continue
            self.log(f"\n=== [{st.id}] {st.title} ===")
            while True:
                t0 = time.time()
                try:
                    res = st.fn(self) or {}
                    rec = {"status": "ok", "title": st.title, "stage": st.stage,
                           "finished": datetime.now().isoformat(timespec="seconds"),
                           "seconds": round(time.time() - t0, 1), **res}
                    break
                except SkipStep:
                    rec = {"status": "skipped", "title": st.title, "stage": st.stage}
                    self.log("  skipped")
                    break
                except StepFailed as exc:
                    self.log(f"  !! {exc}")
                    choice = self._on_failure()
                    if choice == "retry":
                        continue
                    if choice == "skip":
                        rec = {"status": "failed", "title": st.title, "stage": st.stage, "error": str(exc)}
                        break
                    raise Abort()
            self.state["done"][st.id] = {k: ([str(r) for r in v] if k == "runs" else v) for k, v in rec.items()}
            self.save_state()

    def _on_failure(self) -> str:
        if self.on_error == "skip":
            return "skip"
        if self.on_error == "stop" or self.sim:
            return "stop"
        while True:
            a = input("   r = retry, s = skip and carry on, q = quit: ").strip().lower()
            if a in ("r", "s", "q"):
                return {"r": "retry", "s": "skip", "q": "stop"}[a]

    def cleanup(self):
        if self._awg_running:
            try:
                self.script("03_pulsed/awg_oil_patterns.py", "off")
            except Exception as exc:  # pragma: no cover
                self.log(f"  !! could not stop the AWG ({exc}). SWITCH ITS OUTPUTS OFF BY HAND.")
        if self._voa is not None:
            self._voa.close()
        if self._tec is not None:
            if self._tec_at is not None:
                self.log(f"  TEC left ON at {self._tec_at:g} C (lasers are off). "
                         "Disable it with 01_characterisation/set_temperature.py --off when you are done.")
            self._tec.close()


# ======================================================================================
# The plan: which steps, in which order
# ======================================================================================

def _spec(c: Campaign):
    return c.camp.get("characterisation", {})


def plan(c: Campaign, stages: list[str]) -> list[Step]:
    steps: list[Step] = []
    if "characterisation" in stages:
        steps += _characterisation(c)
    if "locking" in stages:
        steps += _locking(c)
    if "pulsed" in stages:
        steps += _pulsed(c)
    if "qkd" in stages:
        steps += _qkd(c)
    steps.append(Step("report", "report", "Build the campaign report", _report))
    return steps


def _fmt(x: float) -> str:
    return f"{x:g}"


# ---- stage 1 ---------------------------------------------------------------------------

def _characterisation(c: Campaign) -> list[Step]:
    s = _spec(c)
    laser = s.get("laser", "DBR852PN")
    temps = [float(t) for t in s.get("temperatures_C", [25.0])]
    out: list[Step] = []

    def check(c):
        args = []
        if c.mode in ("auto", "manual-driver"):
            args.append("--meter")
        if c.mode == "auto":
            args.append("--driver")
        if c.tec_control == "auto":
            args.append("--tec")
        if not args:
            return {}
        c.script("01_characterisation/check_instruments.py", *args)
        return {}

    out.append(Step("c.check", "characterisation", "Check the instruments answer (laser off)", check, needs_bench=True))

    def prep(c):
        c.prompt("Fibre from the master to the POWER METER (attenuator if the sensor needs it). "
                 "Power meter app and Kinesis app CLOSED.")
        return {}

    out.append(Step("c.prep", "characterisation", "Connect the master to the power meter", prep, needs_bench=True))

    for k, T in enumerate(temps):
        def liv(c, T=T, first=(k == 0)):
            c.set_temp(T)
            args = ["--laser", laser, "--temp", _fmt(T), "--stop", _fmt(float(s.get("stop_mA", 200))),
                    "--settle", "0" if c.sim else _fmt(float(s.get("settle_s", 0.5))), "--mode", c.mode_for("li_sweep"), "--yes",
                    "--note", f"campaign {c.folder.name}"]
            if first and s.get("zero_meter", True) and c.mode != "manual":
                args.append("--zero")
            return {"runs": c.script("01_characterisation/li_sweep.py", *args), "temperature_C": T}
        out.append(Step(f"c.liv.{_fmt(T)}C", "characterisation", f"L-I-V sweep at {T:g} C", liv))

    if len(temps) >= 2:
        def tseries(c):
            runs = c.runs("c.liv.")
            if len(runs) < 2:
                raise SkipStep()
            dest = c.data / "analysis" / "temperature_series"
            return {"runs": c.script("01_characterisation/compare_temperatures.py", *runs, "--out", dest)}
        out.append(Step("c.tseries", "characterisation", "Threshold against temperature and T0", tseries))

    if s.get("stability", True):
        def stability(c):
            if c.mode == "manual":
                c.log("  stability logging needs the meter connected; skipped in manual mode")
                raise SkipStep()
            T = float(s.get("stability_temp_C", 25.0))
            c.set_temp(T)
            minutes = 0.02 if c.sim else float(s.get("stability_minutes", 10))
            args = ["--laser", laser, "--temp", _fmt(T), "--current", _fmt(float(s.get("stability_current_mA", 150))),
                    "--minutes", _fmt(minutes), "--mode", c.mode_for("power_stability"), "--yes"]
            return {"runs": c.script("01_characterisation/power_stability.py", *args)}
        out.append(Step("c.stability", "characterisation", "Power stability at one operating point", stability))

    if s.get("tuning", True):
        tune_file = lambda c: c.data / "tuning" / f"tuning_{laser}.csv"  # noqa: E731

        def tuning_prep(c):
            c.prompt("Move the master fibre to the OSA (20-30 dB attenuation in front of it). "
                     "You will type the peak wavelength (and SMSR) at each current.")
            return {}
        out.append(Step("c.tuning.prep", "characterisation", "Connect the master to the OSA", tuning_prep, needs_bench=True))

        for T in [float(t) for t in s.get("tuning_temperatures_C", temps)]:
            def tune(c, T=T):
                c.set_temp(T)
                f = tune_file(c)
                f.parent.mkdir(parents=True, exist_ok=True)
                c.script("01_characterisation/wavelength_log.py", "--laser", laser, "--temp", _fmt(T),
                         "--currents", s.get("tuning_currents", "60:200:10"), "--file", f,
                         "--mode", c.mode_for("wavelength_log"), "--yes")
                res = json.loads(f.with_name(f.stem + "_results.json").read_text())
                per_I = {float(k): v for k, v in res.get("per_current", {}).items()}
                if per_I:
                    ref = float(c.camp.get("locking", {}).get("master_temp_C", 25.0))
                    best = min(per_I, key=lambda t: abs(t - ref))
                    c.set_value("master_tuning_pm_per_mA", per_I[best] * 1000)
                return {"runs": [f.parent], "temperature_C": T}
            out.append(Step(f"c.tuning.{_fmt(T)}C", "characterisation", f"Wavelength vs current at {T:g} C", tune))
    return out


# ---- stage 2 ---------------------------------------------------------------------------

def _locking(c: Campaign) -> list[Step]:
    s = c.camp.get("locking", {})
    Tm = float(s.get("master_temp_C", 25.0))
    out: list[Step] = []

    def setup(c):
        c.prompt("Build the injection path: master -> VOA -> 99:1 B -> circulator 1 -> 2 <-> slave -> 3 -> 99:1 A. "
                 "Slave on its own (>= 1 A) driver, output OFF. VOA control lead connected. "
                 "Power meter on the VOA output for the calibration.")
        return {}
    out.append(Step("l.setup", "locking", "Set up the injection path", setup, needs_bench=True))

    def voa(c):
        c.set_temp(Tm)
        args = ["--master-mA", _fmt(float(s.get("voa_master_mA", 150))), "--step", _fmt(float(s.get("voa_step_V", 0.1))),
                "--mode", c.mode_for("voa_calibration"), "--voa", c.voa_control(), "--yes"]
        if c.mode == "auto":
            args.append("--drive-master")
        runs = c.script("02_injection_locking/voa_calibration.py", *args)
        lookups = [r / "lookup.json" for r in runs if (r / "lookup.json").exists()]
        if not lookups:
            raise StepFailed("VOA calibration did not produce lookup.json")
        c.set_value("voa_lookup", str(lookups[-1]))
        return {"runs": runs}
    out.append(Step("l.voa", "locking", "Calibrate the VOA", voa))

    if s.get("spectra", True):
        def spectra(c):
            if c.sim:
                return {"runs": c.script("02_injection_locking/osa_spectrum.py", "--demo")}
            c.prompt("Move the 1 % tap of coupler A to the OSA. Slave on at its first current, master on.")
            paths = []
            for what in ("FREE-RUNNING slave (VOA at maximum attenuation or master blocked)",
                         "LOCKED slave (master tuned onto a slave mode, low VOA attenuation)"):
                p = c.ask_path(f"Export an OSA trace of the {what} and give its path")
                if p:
                    paths.append(p)
            if not paths:
                raise SkipStep()
            dest = c.data / "spectra"
            dest.mkdir(parents=True, exist_ok=True)
            copies = []
            for p in paths:
                q = dest / p.name
                shutil.copy2(p, q)
                copies.append(q)
            return {"runs": c.script("02_injection_locking/osa_spectrum.py", *copies)}
        out.append(Step("l.spectra", "locking", "Free-running and locked OSA spectra", spectra))

    slave_temp = s.get("slave_temp_C")
    for Is in [float(x) for x in s.get("slave_currents_mA", [400.0])]:
        def slave(c, Is=Is):
            c.prompt(f"Set the SLAVE driver to {Is:g} mA (output on){'' if slave_temp is None else f', slave TEC at {slave_temp:g} C'}. "
                     "OSA on the coupler A tap.")
            return {}
        out.append(Step(f"l.slave.{_fmt(Is)}mA", "locking", f"Slave to {Is:g} mA", slave, needs_bench=True))
        for dB in [float(x) for x in s.get("voa_attenuations_dB", [20.0])]:
            def lmap(c, Is=Is, dB=dB):
                c.set_temp(Tm)
                c.set_voa_dB(dB)
                args = ["--temp", _fmt(Tm), "--slave-mA", _fmt(Is), "--voa-dB", _fmt(dB),
                        "--currents", s.get("master_currents", "80:200:1"), "--mode", c.mode_for("locking_map"), "--yes"]
                if slave_temp is not None:
                    args += ["--slave-temp", _fmt(float(slave_temp))]
                if c.value("master_tuning_pm_per_mA"):
                    args += ["--tuning-pm-per-mA", f"{c.value('master_tuning_pm_per_mA'):.4f}"]
                return {"runs": c.script("02_injection_locking/locking_map.py", *args), "slave_mA": Is, "voa_dB": dB}
            out.append(Step(f"l.map.{_fmt(Is)}mA.{_fmt(dB)}dB", "locking",
                            f"Locking map: slave {Is:g} mA, VOA {dB:g} dB", lmap))

    def theory(c):
        summaries = [r / "summary.json" for r in c.runs("l.map.") if (r / "summary.json").exists()]
        args = ["--alpha", *[_fmt(float(x)) for x in s.get("alpha", [3.0, 5.0])],
                "--length-mm", _fmt(float(s.get("slave_length_mm", 1.0))), "--out", c.data / "analysis" / "locking_theory"]
        if c.value("master_tuning_pm_per_mA"):
            args += ["--tuning-pm-per-mA", f"{c.value('master_tuning_pm_per_mA'):.4f}"]
        if summaries:
            args += ["--measured", *summaries]
        return {"runs": c.script("02_injection_locking/locking_theory.py", *args)}
    out.append(Step("l.theory", "locking", "Measured locking windows against theory", theory))
    return out


# ---- stage 3 ---------------------------------------------------------------------------

def _pulsed(c: Campaign) -> list[Step]:
    s = c.camp.get("pulsed", {})
    out: list[Step] = []

    def awg_check(c):
        c.prompt("AWG CH1 and CH2 to the SCOPE (50 ohm inputs), NOT to the bias tees.")
        c.awg("dp")
        c.prompt("On the scope: CH1 = 10 ns pulses 0 to 1 V every 50 ns; CH2 = +/-0.25 V, 5 ns steps in the gaps. "
                 "If anything is wrong, press q.")
        return {}
    out.append(Step("p.awg", "pulsed", "Start the AWG double-pulse setup and check it on the scope", awg_check, needs_bench=True))

    def connect(c):
        c.awg("off")  # never plug RF into the bias tee while the AWG is driving
        c.prompt("AWG outputs are OFF. Slave driver output OFF. Connect CH1 -> 3 dB pad -> slave bias tee RF; "
                 f"fast photodiode (DET08CFC) on the output tap -> scope CH{s.get('scope_channel', 1)} (50 ohm).")
        c.awg("dp")
        c.prompt("AWG running again. Switch the slave driver on, then set the scope trigger and timebase on the pulses.")
        return {}
    out.append(Step("p.connect", "pulsed", "Connect the AWG to the slave and the photodiode to the scope", connect,
                    needs_bench=True))

    for Ib in [float(x) for x in s.get("slave_bias_mA", [300.0])]:
        def scope(c, Ib=Ib):
            c.prompt(f"Set the slave DC bias to {Ib:g} mA.")
            args = ["--channel", str(int(s.get("scope_channel", 1))), "--shots", str(int(s.get("scope_shots", 20))),
                    "--label", f"slave bias {Ib:g} mA", "--mode", c.mode_for("scope_capture")]
            return {"runs": c.script("03_pulsed/scope_capture.py", *args), "slave_bias_mA": Ib}
        out.append(Step(f"p.scope.{_fmt(Ib)}mA", "pulsed", f"Pulse capture at slave bias {Ib:g} mA", scope))

    def awg_off(c):
        c.awg("off")
        return {}
    out.append(Step("p.off", "pulsed", "Stop the AWG", awg_off, needs_bench=True))
    return out


# ---- stage 4 ---------------------------------------------------------------------------

def _qkd(c: Campaign) -> list[Step]:
    s = c.camp.get("qkd", {})
    out: list[Step] = []
    slots, slot_ns = int(s.get("slots", 64)), float(s.get("slot_ns", 50.0))
    for proto in s.get("protocols", ["cow", "dps"]):
        def pattern(c, proto=proto):
            args = [proto, "--slots", str(slots), "--slot-ns", _fmt(slot_ns)]
            if s.get("seed") is not None:
                args += ["--seed", str(int(s["seed"]))]
            runs = c.script("04_qkd/qkd_patterns.py", *args)
            c.set_value(f"pattern_{proto}", str(runs[-1]))
            return {"runs": runs}
        out.append(Step(f"q.{proto}.pattern", "qkd", f"{proto.upper()}: make the drive pattern", pattern))

        def load(c, proto=proto):
            folder = c.value(f"pattern_{proto}")
            c.prompt(f"Copy ch1_slave.txt and ch2_master.txt from {folder} onto the AWG's USB stick and plug it in. "
                     "Switch the slave driver output OFF while the AWG reloads.")
            c.awg("custom", "--ch1-file", "ch1_slave.txt", "--ch2-file", "ch2_master.txt",
                  "--period-ns", _fmt(slots * slot_ns), "--ch2-amp", _fmt(float(s.get("ch2_amp_V", 0.25))))
            c.prompt("Pattern running. Check it on the scope against pattern.png, then switch the slave back on.")
            return {}
        out.append(Step(f"q.{proto}.load", "qkd", f"{proto.upper()}: load the pattern on the AWG", load, needs_bench=True))

        def tags(c, proto=proto):
            if proto == "bb84":
                c.log("  BB84 QBER needs Bob's basis choices; analysis not implemented")
                raise SkipStep()
            if c.sim:
                runs = c.script("04_qkd/timetag_qber.py", "--demo", proto)
            else:
                ch = (f"data line on channel {s.get('data_channel', 1)}, " if proto == "cow" else "") + \
                     f"interferometer ports on {s.get('monitor_constructive', 2)} (constructive) and " \
                     f"{s.get('monitor_destructive', 3)} (destructive)"
                p = c.ask_path(f"Record time tags for {s.get('acquisition_s', 60):g} s ({ch}). Export a CSV with "
                               "columns channel,time_ps and give its path")
                if p is None:
                    raise SkipStep()
                folder = Path(c.value(f"pattern_{proto}"))
                dest = folder / "tags.csv"
                shutil.copy2(p, dest)
                runs = c.script("04_qkd/timetag_qber.py", dest, "--pattern", folder,
                                "--data-ch", str(s.get("data_channel", 1)),
                                "--mon-c", str(s.get("monitor_constructive", 2)),
                                "--mon-d", str(s.get("monitor_destructive", 3)),
                                "--window-ps", _fmt(float(s.get("detection_window_ps", 1000))))
            res_file = runs[-1] / "qber_results.json"
            res = json.loads(res_file.read_text())
            c.set_value(f"qber_{proto}", res)
            return {"runs": runs}
        out.append(Step(f"q.{proto}.tags", "qkd", f"{proto.upper()}: time tags -> QBER and visibility", tags))

    def awg_off(c):
        c.awg("off")
        return {}
    out.append(Step("q.off", "qkd", "Stop the AWG", awg_off, needs_bench=True))

    def keyrate(c):
        vis = None
        cow = c.value("qber_cow") or {}
        dps = c.value("qber_dps") or {}
        if cow.get("visibility") is not None:
            vis = cow["visibility"]
        elif dps.get("dps_qber_pct") is not None:
            vis = 1 - 2 * dps["dps_qber_pct"] / 100
        args = ["--rep-MHz", _fmt(float(s.get("rep_MHz", 20))), "--out", c.data / "analysis" / "keyrate"]
        if s.get("spools_km"):
            args += ["--spools", *[_fmt(float(x)) for x in s["spools_km"]]]
        if vis is not None and 0 < vis <= 1:
            args += ["--visibility", f"{vis:.4f}"]
        return {"runs": c.script("04_qkd/keyrate.py", *args), "visibility_used": vis}
    out.append(Step("q.keyrate", "qkd", "Expected key rate against fibre length (with the measured visibility)", keyrate))
    return out


def _report(c: Campaign):
    from .report import build_report
    path = build_report(c)
    c.log(f"  Report: {path}")
    return {"runs": [path.parent]}


# ======================================================================================

def apps_holding_usb() -> list[str]:
    """Thorlabs apps that keep the instruments' USB connections (Windows only, best effort)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout.lower()
    except Exception:
        return []
    hits = []
    if "kinesis" in out:
        hits.append("Kinesis")
    if "powermonitor" in out or "optical power monitor" in out or "pm100" in out:
        hits.append("Thorlabs Optical Power Monitor")
    return hits


def preflight(c: Campaign) -> bool:
    if c.sim:
        return True
    apps = apps_holding_usb()
    if apps:
        print(f"\n!! {', '.join(apps)} looks to be running. Close it: it holds the USB connection and the "
              "scripts will not be able to reach the instrument.")
    print(PREFLIGHT)
    return input("All checked? This campaign switches the laser on and off by itself. [type yes]: ").strip().lower() in ("yes", "y")
