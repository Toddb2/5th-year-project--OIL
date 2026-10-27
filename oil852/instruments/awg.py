"""Active Technologies AWG-5064 (T3AWG6K SCPI command set) over pyvisa, LAN or USB.

These are the commands from the double-pulse setup that worked on the bench in October 2026.
Everything is referred to a 50 ohm load. Check levels on the scope into 50 ohm BEFORE the
outputs go anywhere near a bias tee or laser.
"""

from __future__ import annotations


class AWGError(RuntimeError):
    pass


class AWG5064:
    def __init__(self, address: str, max_high_V: float = 1.0, max_low_V: float = -1.0):
        import pyvisa

        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(address)
        self.inst.timeout = 5000
        self.inst.read_termination = self.inst.write_termination = "\n"
        self.idn = self.inst.query("*IDN?").strip()
        self.max_high_V = max_high_V
        self.max_low_V = max_low_V

    def w(self, cmd: str):
        self.inst.write(cmd)

    def errors(self) -> list[str]:
        out = []
        for _ in range(10):
            e = self.inst.query("SYSTem:ERRor?").strip()
            if e.startswith("0") or e.startswith("+0"):
                break
            out.append(e)
        return out

    def _check_levels(self, low: float, high: float):
        if high > self.max_high_V or low < self.max_low_V:
            raise AWGError(f"Levels {low} to {high} V exceed the configured safe range "
                           f"{self.max_low_V} to {self.max_high_V} V (config/bench.toml [awg])")

    def reset_outputs_off(self):
        self.w("*RST")
        self.inst.query("*OPC?")
        for ch in (1, 2):
            self.w(f"OUTPut{ch}:STATe OFF")
            self.w(f"OUTPut{ch}:IMPedance 50")

    def pulse_train(self, ch: int, period_ns: float, width_ns: float, high_V: float, low_V: float = 0.0,
                    edge_ns: float = 1.0):
        self._check_levels(low_V, high_V)
        self.w(f"SOURce{ch}:FUNCtion:SHAPe PULSe")
        self.w(f"SOURce{ch}:PULSe:PERiod {period_ns}ns")
        self.w(f"SOURce{ch}:PULSe:WIDTh {width_ns}ns")
        self.w(f"SOURce{ch}:PULSe:TRANsition:LEADing {edge_ns}ns")
        self.w(f"SOURce{ch}:PULSe:TRANsition:TRAiling {edge_ns}ns")
        self.w(f"SOURce{ch}:VOLTage:LEVel:IMMediate:LOW {low_V}V")
        self.w(f"SOURce{ch}:VOLTage:LEVel:IMMediate:HIGH {high_V}V")
        self.w(f"OUTPut{ch}:DELay 0ns")

    def double_pulse(self, ch: int, period_ns: float, steps):
        """steps: [(amplitude_V, width_ns, delay_ns, edge_ns), (..)]. Pulse 2's delay counts
        from the end of pulse 1 (AWG convention)."""
        for amp, *_ in steps:
            self._check_levels(min(amp, 0), max(amp, 0))
        self.w(f"SOURce{ch}:FUNCtion:SHAPe DOUBLEPULse")
        self.w(f"SOURce{ch}:PULSe:PERiod {period_ns}ns")
        for k, (amp, width, delay, edge) in enumerate(steps, start=1):
            self.w(f"SOURce{ch}:DOUBLEPULSe:PULSe{k}:AMPLitude {amp}V")
            self.w(f"SOURce{ch}:DOUBLEPULSe:PULSe{k}:WIDTh {width}ns")
            self.w(f"SOURce{ch}:DOUBLEPULSe:PULSe{k}:DELay {delay}ns")
            self.w(f"SOURce{ch}:DOUBLEPULSe:PULSe{k}:TRANsition:LEADing {edge}ns")
            self.w(f"SOURce{ch}:DOUBLEPULSe:PULSe{k}:TRANsition:TRAiling {edge}ns")
        self.w(f"OUTPut{ch}:DELay 0ns")

    def from_file(self, ch: int, path_on_awg: str, period_ns: float, high_V: float, low_V: float):
        """Play a waveform file stored on the USB stick plugged into the AWG."""
        self._check_levels(low_V, high_V)
        self.w(f"SOURce{ch}:FUNCtion:SHAPe EFILe")
        self.w(f'SOURce{ch}:FUNCtion:EFILe "{path_on_awg}"')
        self.w(f"SOURce{ch}:PULSe:PERiod {period_ns}ns")
        self.w(f"SOURce{ch}:FREQuency {1e9 / period_ns}Hz")
        self.w(f"SOURce{ch}:VOLTage:LEVel:IMMediate:LOW {low_V}V")
        self.w(f"SOURce{ch}:VOLTage:LEVel:IMMediate:HIGH {high_V}V")
        self.w(f"OUTPut{ch}:DELay 0ns")

    def marker_on_ch1(self):
        self.w("MARKer:LINk1 CCH1")
        self.w("MARKer:STATe1 ON")

    def report(self) -> list[str]:
        lines = []
        for ch in (1, 2):
            shape = self.inst.query(f"SOURce{ch}:FUNCtion:SHAPe?").strip()
            per = float(self.inst.query(f"SOURce{ch}:PULSe:PERiod?")) * 1e9
            hi = float(self.inst.query(f"SOURce{ch}:VOLTage:HIGH?"))
            lo = float(self.inst.query(f"SOURce{ch}:VOLTage:LOW?"))
            lines.append(f"CH{ch}: {shape}, period {per:.1f} ns, low {lo:+.3f} V, high {hi:+.3f} V")
        return lines

    def run(self):
        self.w("OUTPut1:STATe ON")
        self.w("OUTPut2:STATe ON")
        self.w("AFGControl:RUN")
        self.inst.query("*OPC?")

    def stop(self):
        self.w("AFGControl:STOP")
        self.w("OUTPut1:STATe OFF")
        self.w("OUTPut2:STATe OFF")

    def close(self):
        self.inst.close()
        self.rm.close()
