"""Manual stand-ins: you set the current on the KLD101 (front panel or Kinesis app) and
type in readings. Use this if the DLL won't connect, so a session is never lost.
"""

from __future__ import annotations

from .base import DriverReading, DriverStatus


def _ask_float(prompt: str, allow_blank: bool = True) -> float | None:
    while True:
        s = input(prompt).strip()
        if not s and allow_blank:
            return None
        try:
            return float(s)
        except ValueError:
            print("  Please type a number (or press Enter to skip).")


class ManualDriver:
    """Prompts the operator to set each current by hand."""

    def __init__(self, full_scale_mA: float = 230.0):
        self.full_scale_mA = full_scale_mA
        self.setpoint_mA = 0.0
        self._last_v = None
        self._last_pd = None

    def connect(self):
        print("Manual mode: set each current on the KLD101 yourself when asked.")

    def close(self):
        pass

    def status(self) -> DriverStatus:
        return DriverStatus(output_enabled=True, interlock_ok=True, key_switch_on=True,
                            constant_power_mode=False, polarity="cathode_grounded",
                            current_limit_reached=False, open_circuit=False, psu_ok=True)

    def hardware_limit_mA(self):
        return None

    def set_constant_current(self):
        pass

    def enable(self):
        input("Enable the KLD101 output at 0 mA, then press Enter... ")

    def disable(self):
        input("Set the KLD101 to 0 mA and disable the output, then press Enter... ")

    def set_current_mA(self, mA: float):
        self.setpoint_mA = mA
        input(f"Set the KLD101 to {mA:.1f} mA and press Enter... ")

    def read(self) -> DriverReading:
        i = _ask_float(f"  Current shown on the driver [Enter = {self.setpoint_mA:.1f}]: ")
        v = _ask_float("  Forward voltage in V (multimeter) [Enter = skip]: ")
        return DriverReading(current_mA=self.setpoint_mA if i is None else i, voltage_V=v, pd_current_mA=None)


class ManualPowerMeter:
    """Prompts for the power reading shown on the meter."""

    def __init__(self, wavelength_nm: float = 852.0):
        self.wavelength_nm = wavelength_nm
        self.idn = "manual entry"
        self.sensor = "manual entry"
        self.resource = "manual"
        self.average_count = 1

    def zero(self):
        input("Zero the power meter with the laser off, then press Enter... ")

    def set_wavelength(self, nm):
        self.wavelength_nm = nm

    def power_W(self) -> float:
        while True:
            v = _ask_float("  Power on the meter in mW: ", allow_blank=False)
            if v is not None:
                return v / 1000.0

    def close(self):
        pass
