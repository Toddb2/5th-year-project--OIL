"""Read or set the laser temperature through the TTC001.

  python 01_characterisation/set_temperature.py --read           # live reading (Ctrl+C to stop)
  python 01_characterisation/set_temperature.py --to 25          # set, enable, wait until stable
  python 01_characterisation/set_temperature.py --to 20 --mode manual
  python 01_characterisation/set_temperature.py --off            # disable the TEC output

Temperatures are converted to the thermistor's kOhm set point with r25_kohm and beta_K from
config/bench.toml [tec]. Allowed range: [tec] min_C to max_C.
If the temperature runs away from the target after enabling, the script disables the TEC:
TEC+ and TEC- are swapped.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import time  # noqa: E402

from oil852.config import load_config  # noqa: E402
from oil852.instruments.tec import open_tec  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--to", type=float, help="target temperature in deg C")
    g.add_argument("--read", action="store_true")
    g.add_argument("--off", action="store_true")
    p.add_argument("--mode", choices=["auto", "manual", "sim"], default="auto")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    t = cfg.get("tec", {})
    tec = open_tec(cfg, a.mode)
    tec.connect()
    try:
        if a.off:
            tec.disable()
            print("TEC output disabled.")
        elif a.read:
            hist = []
            print("Temperature, TEC current, and the spread over the last 2 minutes (settled = spread under ~0.1 C)")
            while True:
                T = tec.read_C()
                hist = (hist + [(time.time(), T)])[-120:]
                Ts = [x for _, x in hist]
                extra = f"   TEC {tec.tec_current_A() * 1000:+5.0f} mA" if hasattr(tec, "tec_current_A") else ""
                print(f"\r{T:8.3f} C{extra}   last {len(Ts):3d} s: {min(Ts):6.2f} to {max(Ts):6.2f} C "
                      f"(spread {max(Ts) - min(Ts):.2f})   ", end="", flush=True)
                time.sleep(1)
        else:
            print(f"Going to {tec.describe(a.to)}")
            T = tec.go_to(a.to, float(t.get("tolerance_C", 0.05)), float(t.get("hold_s", 30)),
                          float(t.get("timeout_s", 900)), ramp_C_per_min=float(t.get("ramp_C_per_min", 3.0)))
            print(f"Holding {T:.3f} C. The TEC stays on.")
    except KeyboardInterrupt:
        print()
    finally:
        tec.close()


if __name__ == "__main__":
    main()
