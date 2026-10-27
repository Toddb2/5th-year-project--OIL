"""Shared types for the laser driver and power meter wrappers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriverStatus:
    output_enabled: bool
    interlock_ok: bool
    key_switch_on: bool
    constant_power_mode: bool
    polarity: str  # "cathode_grounded" or "anode_grounded"
    current_limit_reached: bool
    open_circuit: bool
    psu_ok: bool
    raw_bits: int = 0

    def blocking_problems(self, expected_polarity: str) -> list[str]:
        """Conditions that always stop a sweep before it starts."""
        issues = []
        if self.polarity != expected_polarity:
            issues.append(f"driver polarity is {self.polarity}, config expects {expected_polarity}. "
                          "Change it in Kinesis (Settings) with the output OFF.")
        if self.constant_power_mode:
            issues.append("driver is in constant-power mode; the sweep needs constant current")
        return issues

    def warnings(self) -> list[str]:
        """Status bits worth a look. Their exact meaning while the output is off varies,
        so they are shown for confirmation rather than treated as hard stops."""
        w = []
        if not self.interlock_ok:
            w.append("interlock bit not set: check pins 1 and 5 are linked on the driver's DB9 plug")
        if not self.key_switch_on:
            w.append("key/enable bit not set on the KLD101")
        if self.open_circuit:
            w.append("open-circuit bit set: check the laser cable and mount wiring")
        if not self.psu_ok:
            w.append("power-supply bit not OK")
        if self.current_limit_reached:
            w.append("current-limit bit already set")
        return w


@dataclass
class DriverReading:
    current_mA: float
    voltage_V: float | None
    pd_current_mA: float | None
