"""Tektronix 4 Series MSO waveform capture over pyvisa (USB or LAN).

Uses the standard Tek waveform-transfer commands (DATa, WFMOutpre, CURVe?).
Set up the trigger and vertical scale on the scope first; this only grabs what is on screen.
"""

from __future__ import annotations

import numpy as np


class TekScope:
    def __init__(self, address: str = ""):
        import pyvisa

        self.rm = pyvisa.ResourceManager()
        if not address:
            cands = [r for r in self.rm.list_resources() if "0x0699" in r.lower()]  # Tektronix USB vendor ID
            if not cands:
                raise RuntimeError("No Tektronix scope found. Set [scope] address in config/bench.toml.")
            address = cands[0]
        self.inst = self.rm.open_resource(address)
        self.inst.timeout = 20000
        self.idn = self.inst.query("*IDN?").strip()

    def single(self, timeout_s: float = 10.0):
        """Arm a single acquisition and wait for it."""
        self.inst.write("ACQuire:STOPAfter SEQuence")
        self.inst.write("ACQuire:STATE ON")
        old = self.inst.timeout
        self.inst.timeout = int(timeout_s * 1000)
        try:
            self.inst.query("*OPC?")
        finally:
            self.inst.timeout = old

    def run(self):
        self.inst.write("ACQuire:STOPAfter RUNSTop")
        self.inst.write("ACQuire:STATE ON")

    def waveform(self, channel: int = 1):
        """Return (time_s, volts) for one channel."""
        n = int(float(self.inst.query("HORizontal:RECOrdlength?")))
        self.inst.write(f"DATa:SOUrce CH{channel}")
        self.inst.write("DATa:ENCdg RIBinary")
        self.inst.write("WFMOutpre:BYT_Nr 2")
        self.inst.write("WFMOutpre:BYT_Or LSB")
        self.inst.write("DATa:STARt 1")
        self.inst.write(f"DATa:STOP {n}")
        xinc = float(self.inst.query("WFMOutpre:XINcr?"))
        xzero = float(self.inst.query("WFMOutpre:XZEro?"))
        ymult = float(self.inst.query("WFMOutpre:YMUlt?"))
        yoff = float(self.inst.query("WFMOutpre:YOFf?"))
        yzero = float(self.inst.query("WFMOutpre:YZEro?"))
        raw = np.array(self.inst.query_binary_values("CURVe?", datatype="h", is_big_endian=False,
                                                     container=np.array), float)
        v = (raw - yoff) * ymult + yzero
        t = xzero + np.arange(raw.size) * xinc
        return t, v

    def close(self):
        self.inst.close()
        self.rm.close()


def synthetic_pulses(period_ns=50.0, width_ns=0.3, n_pulses=20, jitter_ps=8.0, dt_ps=20.0, noise=0.005, seed=0):
    """Fake photodiode trace for testing: Gaussian pulses with timing jitter."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, period_ns * n_pulses, dt_ps / 1000.0) * 1e-9
    v = rng.normal(0, noise, t.size)
    sigma = width_ns / 2.355 * 1e-9
    for k in range(n_pulses):
        c = (k + 0.5) * period_ns * 1e-9 + rng.normal(0, jitter_ps * 1e-12)
        v += 0.2 * np.exp(-0.5 * ((t - c) / sigma) ** 2)
    return t, v
