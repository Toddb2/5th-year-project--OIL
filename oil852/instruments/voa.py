"""VOA control voltage (V800PA, 0-5 V): typed in by hand, from an AWG channel in DC mode, or simulated.

The AWG DC commands are in config/bench.toml [voa] so they can be corrected without touching code.
They have NOT been proven on the bench yet: before the first automatic run, set a voltage with
  python 02_injection_locking/voa_calibration.py --set 2.5 --voa awg
and check it with a multimeter on the VOA control lead (High-Z, so the AWG must be set to High-Z too).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HARD_MAX_V = 5.0  # V800PA control input range


class VOAError(RuntimeError):
    pass


def _check(v: float, max_V: float):
    if v < 0 or v > min(max_V, HARD_MAX_V):
        raise VOAError(f"VOA control {v:g} V outside 0-{min(max_V, HARD_MAX_V):g} V")


class ManualVOA:
    def __init__(self, max_V: float = 5.0):
        self.max_V = max_V
        self.volts = None

    def set_V(self, v: float):
        _check(v, self.max_V)
        input(f"Set the VOA control voltage to {v:.3f} V and press Enter... ")
        self.volts = v

    def close(self):
        pass


class SimVOA:
    def __init__(self, max_V: float = 5.0):
        self.max_V = max_V
        self.volts = 0.0

    def set_V(self, v: float):
        _check(v, self.max_V)
        self.volts = v

    def close(self):
        pass


class AwgDcVOA:
    """One AWG channel used as a DC source. Opens and closes the VISA session on each change so
    it never blocks the pulse scripts, which talk to the same AWG."""

    def __init__(self, address: str, channel: int, max_V: float, setup_cmds: list[str], level_cmd: str,
                 on_cmd: str):
        self.address = address
        self.channel = channel
        self.max_V = max_V
        self.setup_cmds = setup_cmds
        self.level_cmd = level_cmd
        self.on_cmd = on_cmd
        self.volts = None
        self._configured = False

    def set_V(self, v: float):
        _check(v, self.max_V)
        import pyvisa

        rm = pyvisa.ResourceManager()
        inst = rm.open_resource(self.address)
        inst.timeout = 5000
        inst.read_termination = inst.write_termination = "\n"
        try:
            fmt = {"ch": self.channel, "v": v}
            if not self._configured:
                for c in self.setup_cmds:
                    inst.write(c.format(**fmt))
                self._configured = True
            inst.write(self.level_cmd.format(**fmt))
            inst.write(self.on_cmd.format(**fmt))
            self.volts = v
        finally:
            inst.close()
            rm.close()

    def close(self):
        pass


def open_voa(cfg: dict, control: str):
    v = cfg.get("voa", {})
    max_V = float(v.get("max_V", 5.0))
    if control == "sim":
        return SimVOA(max_V)
    if control == "manual":
        return ManualVOA(max_V)
    if control == "awg":
        return AwgDcVOA(v.get("address") or cfg["awg"]["address"], int(v.get("awg_channel", 3)), max_V,
                        list(v.get("setup_cmds", [])), v["level_cmd"], v["on_cmd"])
    raise ValueError(f"Unknown VOA control '{control}' (use manual, awg or sim)")


def voltage_for_dB(lookup_json: Path | str, attenuation_dB: float) -> float:
    """Control voltage that gives an attenuation (relative to minimum) from a voa_calibration run."""
    d = json.loads(Path(lookup_json).read_text())
    if "curve" not in d:
        raise VOAError(f"{lookup_json} has no calibration curve; re-run voa_calibration.py")
    V = np.asarray(d["curve"]["control_V"], float)
    att = np.maximum.accumulate(np.asarray(d["curve"]["attenuation_dB"], float))
    if attenuation_dB > att.max() + 1e-9:
        raise VOAError(f"{attenuation_dB:g} dB is beyond the calibrated maximum {att.max():.1f} dB")
    # first voltage at which the monotone curve reaches the target
    return float(np.interp(attenuation_dB, att, V))
