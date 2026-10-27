"""Check the power meter and KLD101 talk to the laptop, without switching the laser on.

  python 01_characterisation/check_instruments.py            # both
  python 01_characterisation/check_instruments.py --meter    # power meter only
  python 01_characterisation/check_instruments.py --driver   # KLD101 only
"""

from __future__ import annotations

import argparse

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package
from oil852.cli import ROOT  # noqa: F401

from oil852.config import load_config


def check_meter(cfg):
    import pyvisa

    rm = pyvisa.ResourceManager()
    print("VISA resources:", rm.list_resources() or "none")
    from oil852.instruments.pm100 import PM100

    m = PM100(cfg["power_meter"].get("resource", ""), 852.0, 10)
    print(f"Power meter: {m.idn}\n  resource {m.resource}\n  sensor   {m.sensor}\n  wavelength {m.wavelength_nm} nm")
    print(f"  reading now: {m.power_W() * 1e3:.4f} mW (laser should be off: this is the dark level)")
    m.close()


def check_driver(cfg):
    from oil852.instruments.kld101 import KLD101

    d = cfg["driver"]
    k = KLD101(d["serial"], d["kinesis_path"], d["full_scale_mA"], d.get("voltage_counts_per_V", 1000.0))
    k.connect()
    st = k.status()
    print(f"KLD101 {d['serial']}: status bits 0x{st.raw_bits:08X}")
    for field in ("output_enabled", "interlock_ok", "key_switch_on", "constant_power_mode", "polarity",
                  "current_limit_reached", "open_circuit", "psu_ok"):
        print(f"  {field:22s} {getattr(st, field)}")
    hw = k.hardware_limit_mA()
    print(f"  current limit on K-Cube ~{hw:.0f} mA" if hw else "  current limit: not read")
    rd = k.read()
    print(f"  current {rd.current_mA:.2f} mA, voltage {rd.voltage_V}, PD {rd.pd_current_mA}")
    for issue in st.blocking_problems(d["polarity"]) + st.warnings():
        print(f"  ! {issue}")
    k.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--meter", action="store_true")
    p.add_argument("--driver", action="store_true")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    both = not (a.meter or a.driver)
    if a.meter or both:
        try:
            check_meter(cfg)
        except Exception as exc:
            print(f"Power meter: FAILED ({exc})")
    if a.driver or both:
        try:
            check_driver(cfg)
        except Exception as exc:
            print(f"KLD101: FAILED ({exc})")


if __name__ == "__main__":
    main()
