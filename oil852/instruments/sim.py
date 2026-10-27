"""Simulated laser, driver and power meter, so every script can be tried away from the bench.

The default model is roughly a DBR852PN: threshold 50 mA at 25 C, slope 0.09 W/A,
turn-on voltage about 1.45 V with a few ohms of series resistance.
"""

from __future__ import annotations

import math
import random

from .base import DriverReading, DriverStatus


class SimLaser:
    def __init__(self, ith_25C_mA=50.0, T0_K=120.0, slope_W_per_A=0.09, slope_drop_per_C=0.004,
                 v_turn_on=1.45, r_series=4.0, ideality_V=0.04, pd_A_per_W=0.01,
                 lambda0_nm=852.0, tune_nm_per_mA=0.002, tune_nm_per_C=0.06, noise=0.003, seed=1):
        self.ith_25C_mA = ith_25C_mA
        self.T0_K = T0_K
        self.slope = slope_W_per_A
        self.slope_drop_per_C = slope_drop_per_C
        self.v_turn_on = v_turn_on
        self.r_series = r_series
        self.ideality_V = ideality_V
        self.pd_A_per_W = pd_A_per_W
        self.lambda0_nm = lambda0_nm
        self.tune_I = tune_nm_per_mA
        self.tune_T = tune_nm_per_C
        self.noise = noise
        self.temperature_C = 25.0
        self.rng = random.Random(seed)

    def threshold_mA(self) -> float:
        return self.ith_25C_mA * math.exp((self.temperature_C - 25.0) / self.T0_K)

    def power_W(self, I_mA: float) -> float:
        ith = self.threshold_mA()
        eta = self.slope * (1 - self.slope_drop_per_C * (self.temperature_C - 25.0))
        spont = 2e-6 * I_mA / max(ith, 1e-9)  # weak LED-like emission below threshold
        p = spont + (eta * (I_mA - ith) / 1000.0 if I_mA > ith else 0.0)
        return max(p * (1 + self.rng.gauss(0, self.noise)), 0.0)

    def voltage_V(self, I_mA: float) -> float:
        if I_mA <= 0:
            return 0.0
        I = I_mA / 1000.0
        return self.v_turn_on + self.ideality_V * math.log1p(I / 1e-4) + I * self.r_series

    def wavelength_nm(self, I_mA: float) -> float:
        return self.lambda0_nm + self.tune_I * (I_mA - 100) + self.tune_T * (self.temperature_C - 25.0)


class SimDriver:
    def __init__(self, laser: SimLaser, full_scale_mA: float = 230.0, limit_mA: float = 230.0):
        self.laser = laser
        self.full_scale_mA = full_scale_mA
        self.limit_mA = limit_mA
        self.enabled = False
        self.setpoint_mA = 0.0

    def connect(self):
        pass

    def close(self):
        pass

    def status(self) -> DriverStatus:
        return DriverStatus(output_enabled=self.enabled, interlock_ok=True, key_switch_on=True,
                            constant_power_mode=False, polarity="cathode_grounded",
                            current_limit_reached=self.setpoint_mA >= self.limit_mA,
                            open_circuit=False, psu_ok=True)

    def hardware_limit_mA(self):
        return self.limit_mA

    def set_constant_current(self):
        pass

    def enable(self):
        self.enabled = True

    def disable(self):
        self.setpoint_mA = 0.0
        self.enabled = False

    def set_current_mA(self, mA: float):
        self.setpoint_mA = min(mA, self.limit_mA)

    def actual_mA(self) -> float:
        return self.setpoint_mA if self.enabled else 0.0

    def read(self) -> DriverReading:
        I = self.actual_mA()
        p = self.laser.power_W(I)
        return DriverReading(current_mA=I + random.gauss(0, 0.05), voltage_V=self.laser.voltage_V(I),
                             pd_current_mA=p * self.laser.pd_A_per_W * 1000.0)


class SimPowerMeter:
    def __init__(self, driver: SimDriver, wavelength_nm: float = 852.0):
        self.driver = driver
        self.wavelength_nm = wavelength_nm
        self.idn = "SIMULATED,PM100D"
        self.sensor = "SIMULATED,S120C"
        self.resource = "sim"
        self.average_count = 1

    def zero(self):
        pass

    def set_wavelength(self, nm):
        self.wavelength_nm = nm

    def power_W(self) -> float:
        return self.driver.laser.power_W(self.driver.actual_mA())

    def close(self):
        pass
