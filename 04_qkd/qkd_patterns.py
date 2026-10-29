"""Make AWG waveform files for a QKD protocol from random bits, plus the record of what was sent.

  python 04_qkd/qkd_patterns.py cow  --slots 64 --decoy 0.1
  python 04_qkd/qkd_patterns.py dps  --slots 64
  python 04_qkd/qkd_patterns.py bb84 --slots 64      # step levels: see oil852/patterns.py (confirm the mapping first)

Writes into data/qkd_patterns/<protocol>_<time>/:
  ch1_slave.txt, ch2_master.txt   load with Wave. List; set the AWG period to slots x slot_ns
  sent.csv                        slot-by-slot record; 04_qkd/timetag_qber.py needs it
  pattern.png                     the two channels, for checking against the scope

Limitation: the AWG repeats the file, so the "random" pattern repeats every slots x slot_ns.
That is fine for QBER and visibility tests, but a real key needs a non-repeating source
(streaming the AWG sequencer, or a pattern generator) and is out of scope here.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from oil852.config import DATA_ROOT  # noqa: E402
from oil852.runio import log_run  # noqa: E402
from oil852.patterns import (MAX_SAMPLES, bb84_steps, cow_slots, dps_steps, master_waveform,  # noqa: E402
                             random_bb84_symbols, save_awg_file, slave_waveform)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("protocol", choices=["cow", "dps", "bb84"])
    p.add_argument("--slots", type=int, default=64, help="time slots in the pattern (COW: must be even)")
    p.add_argument("--slot-ns", type=float, default=50.0)
    p.add_argument("--samples-per-slot", type=int, default=200)
    p.add_argument("--pulse-ns", type=float, default=10.0, help="slave drive pulse width")
    p.add_argument("--step-ns", type=float, default=5.0, help="master step width")
    p.add_argument("--decoy", type=float, default=0.1, help="COW decoy fraction")
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()
    if a.slots * a.samples_per_slot > MAX_SAMPLES:
        _sys.exit(f"{a.slots} slots x {a.samples_per_slot} samples > {MAX_SAMPLES}. Lower one of them.")
    rng = np.random.default_rng(a.seed)
    rows = []
    if a.protocol == "cow":
        n_bits = a.slots // 2
        bits = rng.integers(0, 2, n_bits)
        slave, labels = cow_slots(bits, a.decoy, rng)
        master = np.zeros(a.slots)
        for k, lab in enumerate(labels):
            for j in (0, 1):
                rows.append({"slot": 2 * k + j, "slave_pulse": int(slave[2 * k + j]), "master_step": 0.0,
                             "bit_index": k, "symbol": lab})
    elif a.protocol == "dps":
        bits = rng.integers(0, 2, a.slots)
        slave = np.ones(a.slots)
        master = dps_steps(bits)
        for k in range(a.slots):
            # step in slot k sets the phase of pulse k+1 relative to pulse k
            rows.append({"slot": k, "slave_pulse": 1, "master_step": float(master[k]), "bit_index": k,
                         "symbol": int(bits[k])})
    else:
        syms = random_bb84_symbols(a.slots, rng)
        slave = np.ones(a.slots)
        master = bb84_steps(syms)
        for k, s in enumerate(syms):
            rows.append({"slot": k, "slave_pulse": 1, "master_step": float(master[k]), "bit_index": k, "symbol": s})

    sps = a.samples_per_slot
    y1 = slave_waveform(slave, sps, a.pulse_ns / a.slot_ns)
    y2 = master_waveform(master, sps, a.step_ns / a.slot_ns)
    out = DATA_ROOT / "qkd_patterns" / f"{a.protocol}_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    log_run(out)
    save_awg_file(out / "ch1_slave.txt", y1)
    peak2 = save_awg_file(out / "ch2_master.txt", y2) if np.any(y2) else 1.0
    if not np.any(y2):
        np.savetxt(out / "ch2_master.txt", y2, fmt="%.5f")
    with open(out / "sent.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    period = a.slots * a.slot_ns
    meta = {"protocol": a.protocol, "slots": a.slots, "slot_ns": a.slot_ns, "period_ns": period,
            "samples_per_slot": sps, "sample_ns": a.slot_ns / sps, "seed": a.seed,
            "ch2_normalised_by": peak2,
            "awg_settings": {"CH1": f"period {period:g} ns, High 1.0 V, Low 0 V",
                             "CH2": "period same as CH1; High/Low = +/- the step amplitude that gives a pi phase step"}}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    t = np.arange(len(y1)) * a.slot_ns / sps
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 4), sharex=True)
    ax1.plot(t, y1, lw=0.8)
    ax1.set_ylabel("CH1 slave")
    ax2.plot(t, y2, lw=0.8, color="#d1495b")
    ax2.set_ylabel("CH2 master")
    ax2.set_xlabel("Time (ns)")
    ax1.set_title(f"{a.protocol.upper()} pattern, {a.slots} slots, period {period:g} ns")
    fig.tight_layout()
    fig.savefig(out / "pattern.png", dpi=150)
    print(f"Saved {out}\nSet both AWG channels to a period of {period:g} ns.")


if __name__ == "__main__":
    main()
