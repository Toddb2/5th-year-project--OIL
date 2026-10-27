"""Thorlabs PM100-series power meter (PM100D, PM100USB, PM100A) over VISA/SCPI.

On Windows, the meter must use the NI-VISA driver: run Thorlabs' "Power Meter Driver
Switcher" and pick PM100D (NI-VISA) if pyvisa cannot see it. On Linux/macOS,
`pip install pyvisa-py pyusb` works without NI-VISA.
"""

from __future__ import annotations

import time

THORLABS_VID = "0x1313"


class PM100Error(RuntimeError):
    pass


class PM100:
    def __init__(self, resource: str = "", wavelength_nm: float = 852.0, average_count: int = 50):
        import pyvisa  # imported here so --sim runs without pyvisa installed

        self._rm = pyvisa.ResourceManager()
        if not resource:
            candidates = [r for r in self._rm.list_resources() if THORLABS_VID in r.lower() or "1313" in r]
            if not candidates:
                raise PM100Error("No Thorlabs power meter found over VISA. Check USB, and on Windows use the "
                                 "Power Meter Driver Switcher to select the NI-VISA driver.")
            resource = candidates[0]
        self.resource = resource
        self.inst = self._rm.open_resource(resource)
        self.inst.timeout = 5000
        self.idn = self.inst.query("*IDN?").strip()
        try:
            self.sensor = self.inst.query("SYST:SENS:IDN?").strip()
        except Exception:
            self.sensor = "unknown"
        self.inst.write("SENS:POW:UNIT W")
        self.set_wavelength(wavelength_nm)
        self.set_average(average_count)

    def set_wavelength(self, nm: float):
        self.inst.write(f"SENS:CORR:WAV {nm:.1f}")
        got = float(self.inst.query("SENS:CORR:WAV?"))
        if abs(got - nm) > 0.5:
            raise PM100Error(f"Meter wavelength is {got} nm, wanted {nm} nm")
        self.wavelength_nm = got

    def set_average(self, n: int):
        self.inst.write(f"SENS:AVER:COUN {int(n)}")
        self.average_count = int(n)

    def zero(self):
        """Dark zero. Laser must be OFF or the fibre disconnected."""
        self.inst.write("SENS:CORR:COLL:ZERO:INIT")
        for _ in range(100):
            time.sleep(0.2)
            try:
                if int(self.inst.query("SENS:CORR:COLL:ZERO:STAT?")) == 0:
                    return
            except Exception:
                time.sleep(3)
                return
        raise PM100Error("Zeroing did not finish")

    def power_W(self) -> float:
        return float(self.inst.query("MEAS:POW?"))

    def close(self):
        try:
            self.inst.close()
        finally:
            self._rm.close()
