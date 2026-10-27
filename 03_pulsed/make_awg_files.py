"""Write the basic AWG waveform files to load from a USB stick (Wave. List > Import).

  python 03_pulsed/make_awg_files.py                 # into data/awg_files/
  python 03_pulsed/make_awg_files.py --out E:\\       # straight onto the stick

Files (each = four 50 ns slots = 200 ns; set the AWG period to 200 ns):
  ch1_slave_pulses.txt   10 ns pulse at the start of every slot.        High 1.0 V,  Low 0 V
  ch2_master_dps.txt     5 ns steps in the gaps: up, down, none, up.    High +0.25 V, Low -0.25 V
  ch2_master_bb84.txt    steps +0.5, -1.0, -0.25, 0 (relative).         High +0.5 V,  Low -0.5 V
For random-bit protocol patterns (COW, DPS, BB84) use 04_qkd/qkd_patterns.py.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

from oil852.config import DATA_ROOT  # noqa: E402
from oil852.patterns import render, save_awg_file  # noqa: E402

SPS = 1000  # samples per 50 ns slot = 0.05 ns resolution, 4000 samples per file


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=DATA_ROOT / "awg_files")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    files = {
        "ch1_slave_pulses.txt": render([1, 1, 1, 1], SPS, 0.0, 0.20),
        "ch2_master_dps.txt": render([1, -1, 0, 1], SPS, 0.5, 0.10),
        "ch2_master_bb84.txt": render([0.5, -1, -0.25, 0], SPS, 0.5, 0.10),
    }
    for name, y in files.items():
        save_awg_file(a.out / name, y)
        print(f"wrote {a.out / name} ({len(y)} samples)")
    (a.out / "README.txt").write_text(__doc__)


if __name__ == "__main__":
    main()
