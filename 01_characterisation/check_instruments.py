"""Check the power meter, KLD101 and TTC001 talk to the laptop, without switching the laser on.

  python 01_characterisation/check_instruments.py            # meter, KLD101 and TTC001
  python 01_characterisation/check_instruments.py --meter    # power meter only
  python 01_characterisation/check_instruments.py --driver   # KLD101 only
  python 01_characterisation/check_instruments.py --tec      # TTC001 only
  python 01_characterisation/check_instruments.py --all      # also try the AWG and scope

Close the Kinesis app and the Thorlabs power meter app first: each holds its USB connection.
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
    try:
        _report_driver(k, d)
    finally:
        k.close()


def _report_driver(k, d):
    st = k.status()
    print(f"KLD101 {d['serial']}: status bits 0x{st.raw_bits:08X}")
    for field in ("output_enabled", "interlock_ok", "key_switch_on", "constant_power_mode", "polarity",
                  "current_limit_reached", "open_circuit", "psu_ok"):
        print(f"  {field:22s} {getattr(st, field)}")
    hw = k.hardware_limit_mA()
    print(f"  current limit on K-Cube ~{hw:.0f} mA" if hw else
          "  current limit: not readable with this Kinesis version (check it says 200 mA in Kinesis)")
    extras = sorted(set(("LD_SetOpenLoopMode", "LD_GetLaserDiodeCurrentReading", "LD_GetVoltageReading",
                         "LD_GetPhotoCurrentReading", "LD_GetMaxCurrentDigPot")) - k._has)
    if extras:
        print(f"  not in this Kinesis version: {', '.join(extras)}")
    rd = k.read()
    print(f"  current {rd.current_mA:.2f} mA, voltage {rd.voltage_V}, PD {rd.pd_current_mA}")
    for issue in st.blocking_problems(d["polarity"]) + st.warnings():
        print(f"  ! {issue}")


def check_tec(cfg):
    from oil852.instruments.tec import open_tec

    tec = open_tec(cfg, "auto")
    tec.connect()
    try:
        _report_tec(tec, cfg)
    finally:
        tec.close()


def _report_tec(tec, cfg):
    print(f"TTC001 {cfg['tec']['serial']}: sensor {tec.sensor}")
    print(f"  reading {tec.read_display():.2f} kOhm = {tec.read_C():.2f} C, set point {tec.setpoint_C():.2f} C, "
          f"TEC current {tec.tec_current_A() * 1000:.0f} mA, limit {tec.current_limit_A():.2f} A")


def check_others(cfg):
    from oil852.instruments.awg import AWG5064
    from oil852.instruments.tek_scope import TekScope

    for name, make in (("AWG", lambda: AWG5064(cfg["awg"]["address"])),
                       ("Scope", lambda: TekScope(cfg["scope"].get("address", "")))):
        try:
            inst = make()
            print(f"{name}: {inst.idn}")
            inst.close()
        except Exception as exc:
            print(f"{name}: not reached ({exc}) - only needed from stage 2/3")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--meter", action="store_true")
    p.add_argument("--driver", action="store_true")
    p.add_argument("--tec", action="store_true")
    p.add_argument("--all", action="store_true", help="also try the AWG and scope")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    every = not (a.meter or a.driver or a.tec)
    failed = False
    for flag, name, fn in ((a.meter, "Power meter", check_meter), (a.driver, "KLD101", check_driver),
                           (a.tec, "TTC001", check_tec)):
        if flag or every:
            try:
                fn(cfg)
            except Exception as exc:
                failed = True
                print(f"{name}: FAILED ({exc})")
    if a.all:
        check_others(cfg)
    _sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
