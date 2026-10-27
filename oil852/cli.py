"""Shared helpers for the command-line scripts in each stage folder."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODES = ["auto", "manual-driver", "manual", "sim"]
MODE_HELP = ("auto = KLD101 and power meter both controlled by the script; "
             "manual-driver = you set the current, the script reads the meter; "
             "manual = you type everything in; sim = simulated laser for practice")


def add_common_args(p):
    p.add_argument("--laser", default="DBR852PN", help="laser name from config/bench.toml (default DBR852PN)")
    p.add_argument("--temp", type=float, required=True, help="TEC set point in deg C (used to label the run)")
    p.add_argument("--mode", choices=MODES, default="auto", help=MODE_HELP)
    p.add_argument("--config", default=None, help="path to an alternative bench.toml")
    p.add_argument("--yes", action="store_true", help="skip the pre-flight confirmation (not recommended)")


def confirm(prompt: str, skip: bool = False) -> bool:
    if skip:
        return True
    return input(f"{prompt} [type yes]: ").strip().lower() in ("yes", "y")


PREFLIGHT = """
Pre-flight checklist
  [ ] Laser goggles on (OD >= 3 at 852 nm). ESD strap on if you touch the mount.
  [ ] TEC controller ON and stable at the set point (thermistor near 10 kohm at 25 C), TEC limit set.
  [ ] Fibre end cleaned and connected to the power sensor (or attenuator); no bare fibre pointing anywhere.
  [ ] Power meter wavelength 852 nm. Sensor can take the expected power.
  [ ] KLD101: constant current, cathode grounded, current limit set, Kinesis app CLOSED (it holds the USB).
"""
