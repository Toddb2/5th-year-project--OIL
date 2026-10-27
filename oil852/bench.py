"""Build the driver and power meter for a run, and keep the laser safe while sweeping."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import LaserSpec


def open_instruments(cfg: dict, mode: str, wavelength_nm: float = 852.0, sim_temperature_C: float = 25.0):
    """mode: 'auto' (KLD101 + PM100), 'manual-driver' (you set current, meter is read),
    'manual' (everything typed in), or 'sim'."""
    dcfg, pcfg = cfg["driver"], cfg["power_meter"]
    if mode == "sim":
        from .instruments.sim import SimDriver, SimLaser, SimPowerMeter
        laser = SimLaser()
        laser.temperature_C = sim_temperature_C
        driver = SimDriver(laser, full_scale_mA=dcfg["full_scale_mA"], limit_mA=dcfg["full_scale_mA"])
        meter = SimPowerMeter(driver, wavelength_nm)
        return driver, meter
    if mode == "manual":
        from .instruments.manual import ManualDriver, ManualPowerMeter
        return ManualDriver(dcfg["full_scale_mA"]), ManualPowerMeter(wavelength_nm)

    from .instruments.pm100 import PM100
    meter = PM100(pcfg.get("resource", ""), wavelength_nm, int(pcfg.get("average_count", 50)))
    if mode == "manual-driver":
        from .instruments.manual import ManualDriver
        return ManualDriver(dcfg["full_scale_mA"]), meter
    if mode == "auto":
        from .instruments.kld101 import KLD101
        driver = KLD101(dcfg["serial"], dcfg["kinesis_path"], dcfg["full_scale_mA"],
                        dcfg.get("voltage_counts_per_V", 1000.0))
        return driver, meter
    raise ValueError(f"Unknown mode {mode}")


@dataclass
class Limits:
    max_current_mA: float
    sensor_max_W: float

    @classmethod
    def build(cls, cfg: dict, spec: LaserSpec, requested_stop_mA: float, hardware_limit_mA: float | None):
        if spec.max_current_mA <= 0:
            raise SystemExit(f"{spec.name} is not allowed on this driver (max_current_mA = 0 in config). "
                             "The FPL852P needs a driver that reaches about 1 A.")
        ceiling = min(spec.max_current_mA, float(cfg["driver"]["full_scale_mA"]))
        if requested_stop_mA > ceiling:
            raise SystemExit(f"--stop {requested_stop_mA} mA is above the {spec.name} limit of {ceiling} mA.")
        if hardware_limit_mA is not None and requested_stop_mA > hardware_limit_mA + 0.5:
            raise SystemExit(f"--stop {requested_stop_mA} mA is above the current limit set on the KLD101 "
                             f"(~{hardware_limit_mA:.0f} mA). Lower --stop or raise the limit on the K-Cube.")
        return cls(max_current_mA=requested_stop_mA,
                   sensor_max_W=float(cfg["power_meter"]["sensor_max_mW"]) / 1000.0)


def ramp_to(driver, target_mA: float, from_mA: float, step_mA: float = 5.0, dwell_s: float = 0.15):
    """Move the current gently instead of jumping."""
    if abs(target_mA - from_mA) <= step_mA:
        driver.set_current_mA(target_mA)
        return
    n = int(abs(target_mA - from_mA) // step_mA)
    direction = 1 if target_mA > from_mA else -1
    for k in range(1, n + 1):
        driver.set_current_mA(from_mA + direction * k * step_mA)
        time.sleep(dwell_s)
    driver.set_current_mA(target_mA)


def safe_shutdown(driver, from_mA: float, manual: bool = False) -> bool:
    """Ramp to zero and disable. Never raises. Returns True if the driver confirmed it."""
    try:
        if not manual and from_mA > 0:
            ramp_to(driver, 0.0, from_mA, step_mA=10.0, dwell_s=0.1)
        driver.disable()
        return True
    except BaseException as exc:  # pragma: no cover - last-ditch path
        print(f"\n!! Could not switch the driver off cleanly ({exc!r}). TURN THE KLD101 OUTPUT OFF BY HAND.")
        return False
