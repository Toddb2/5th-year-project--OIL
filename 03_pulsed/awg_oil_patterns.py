"""Drive the AWG-5064 for the OIL bench from the laptop (LAN or USB).

  python 03_pulsed/awg_oil_patterns.py dp           # CH1 slave pulses + CH2 double-pulse +/- master steps (the setup proven on the bench)
  python 03_pulsed/awg_oil_patterns.py files        # CH1/CH2 from waveform files on the USB stick in the AWG (DPS test steps)
  python 03_pulsed/awg_oil_patterns.py files bb84   # BB84 test step set instead
  python 03_pulsed/awg_oil_patterns.py off          # stop and switch both outputs off
  python 03_pulsed/awg_oil_patterns.py custom --ch1-file ch1_slave.txt --ch2-file ch2_master.txt --period-ns 3200 --ch2-amp 0.25
                                                    # protocol files from 04_qkd/qkd_patterns.py (copied to the stick)

Levels are into 50 ohm. ALWAYS check on the scope (50 ohm input) before connecting the bias tee.
Make the waveform files with 03_pulsed/make_awg_files.py and copy them to the stick.
The AWG address and stick drive letter live in config/bench.toml [awg].
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402

from oil852.config import load_config  # noqa: E402
from oil852.instruments.awg import AWG5064  # noqa: E402

SLAVE_PERIOD_NS = 50.0
SLAVE_WIDTH_NS = 10.0
SLAVE_HIGH_V = 1.0
STEP_WIDTH_NS = 5.0
STEP_AMP_V = 0.25
EDGE_NS = 1.0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["dp", "files", "custom", "off"])
    p.add_argument("pattern", nargs="?", default="dps", choices=["dps", "bb84"])
    p.add_argument("--ch1-file", default="ch1_slave.txt", help="custom: CH1 file name on the stick")
    p.add_argument("--ch2-file", default="ch2_master.txt", help="custom: CH2 file name on the stick")
    p.add_argument("--period-ns", type=float, default=None, help="custom: file period (slots x slot length)")
    p.add_argument("--ch2-amp", type=float, default=STEP_AMP_V, help="custom: CH2 +/- level in V")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)["awg"]
    awg = AWG5064(cfg["address"], cfg.get("max_high_V", 1.0), cfg.get("max_low_V", -1.0))
    print("AWG:", awg.idn)
    try:
        if a.mode == "off":
            awg.stop()
            print("stopped, outputs off")
            return
        awg.reset_outputs_off()
        if a.mode == "dp":
            awg.pulse_train(1, SLAVE_PERIOD_NS, SLAVE_WIDTH_NS, SLAVE_HIGH_V, 0.0, EDGE_NS)
            gap_centre = SLAVE_WIDTH_NS + (SLAVE_PERIOD_NS - SLAVE_WIDTH_NS) / 2
            d1 = gap_centre - STEP_WIDTH_NS / 2
            d2 = SLAVE_PERIOD_NS - STEP_WIDTH_NS  # pulse 2 delay counts from the end of pulse 1
            awg.double_pulse(2, 2 * SLAVE_PERIOD_NS, [(+STEP_AMP_V, STEP_WIDTH_NS, d1, EDGE_NS),
                                                       (-STEP_AMP_V, STEP_WIDTH_NS, d2, EDGE_NS)])
        elif a.mode == "custom":
            if not a.period_ns:
                p.error("custom needs --period-ns (printed by qkd_patterns.py)")
            drive = cfg["usb_drive"]
            awg.from_file(1, f"{drive}{a.ch1_file}", a.period_ns, SLAVE_HIGH_V, 0.0)
            awg.from_file(2, f"{drive}{a.ch2_file}", a.period_ns, a.ch2_amp, -a.ch2_amp)
        else:
            period = 4 * SLAVE_PERIOD_NS  # each file holds four slots
            hi = {"dps": STEP_AMP_V, "bb84": 2 * STEP_AMP_V}[a.pattern]
            drive = cfg["usb_drive"]
            awg.from_file(1, f"{drive}ch1_slave_pulses.txt", period, SLAVE_HIGH_V, 0.0)
            awg.from_file(2, f"{drive}ch2_master_{a.pattern}.txt", period, hi, -hi)
        awg.marker_on_ch1()
        for e in awg.errors():
            print("  AWG error:", e)
        for line in awg.report():
            print(line)
        awg.run()
        for e in awg.errors():
            print("  AWG error:", e)
        print("Running. 'python 03_pulsed/awg_oil_patterns.py off' stops it.")
    finally:
        awg.close()


if __name__ == "__main__":
    main()
