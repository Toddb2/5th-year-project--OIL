"""QBER and visibility from time-tagger data, using the sent-pattern record.

Time tags: a CSV with columns channel,time_ps (one row per detection). Channels:
  --data-ch        data line detector (COW: time of arrival)
  --mon-c/--mon-d  the two outputs of Bob's delay-line interferometer
                   (constructive = phase difference 0, destructive = pi)
The pattern repeats every period (slots x slot length). Detections are folded onto that period
after subtracting --offset-ps, which lines up slot 0 (find it from a histogram, or use --find-offset).

  python 04_qkd/timetag_qber.py tags.csv --pattern data/qkd_patterns/cow_XXXX --data-ch 1 --mon-c 2 --mon-d 3
  python 04_qkd/timetag_qber.py --demo cow     # synthetic tags to see what the output looks like

COW: data-line QBER (bit from which slot of the pair clicked) and monitoring visibility.
DPS: QBER from which interferometer port clicked, compared with the phase step sent.
BB84 needs Bob's basis choice as well, so it is not covered yet.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from oil852.config import DATA_ROOT  # noqa: E402


def fold(times_ps, offset_ps, slot_ps, n_slots):
    phase = (np.asarray(times_ps, float) - offset_ps) % (slot_ps * n_slots)
    slot = (phase // slot_ps).astype(int)
    within = phase - slot * slot_ps
    return slot, within


def find_offset(times_ps, slot_ps, n_slots, sent, window_ps):
    """Offset that puts the most detections inside the pulse windows of occupied slots."""
    occupied = np.array(sent["slave_pulse"].to_numpy(), bool)
    best, best_n = 0.0, -1
    for off in np.arange(0, slot_ps, max(window_ps / 4, 10)):
        slot, within = fold(times_ps, off, slot_ps, n_slots)
        n = int(np.sum(occupied[slot] & (within < window_ps)))
        if n > best_n:
            best, best_n = off, n
    return float(best)


def cow_analysis(tags, sent, meta, a):
    slot_ps = meta["slot_ns"] * 1000
    n = meta["slots"]
    d = tags[tags.channel == a.data_ch].time_ps.to_numpy()
    off = a.offset_ps if a.offset_ps is not None else find_offset(d, slot_ps, n, sent, a.window_ps)
    slot, within = fold(d, off, slot_ps, n)
    keep = within < a.window_ps
    slot = slot[keep]
    bit_index = slot // 2
    measured = slot % 2  # first slot of the pair -> bit 0, second -> bit 1
    labels = sent.groupby("bit_index").symbol.first()
    sent_bits = labels.reindex(bit_index).to_numpy()
    valid = np.array([s in ("0", "1", 0, 1) for s in sent_bits])
    sb = np.array([int(s) for s in sent_bits[valid]])
    errors = int(np.sum(sb != measured[valid]))
    total = int(valid.sum())
    out = {"offset_ps": off, "data_detections_in_window": int(keep.sum()),
           "data_bits_compared": total, "data_qber_pct": 100 * errors / total if total else None}
    out.update(monitor_visibility(tags, a))
    return out


def monitor_visibility(tags, a):
    if a.mon_c is None or a.mon_d is None:
        return {}
    c = int(np.sum(tags.channel == a.mon_c))
    dd = int(np.sum(tags.channel == a.mon_d))
    v = (c - dd) / (c + dd) if c + dd else None
    return {"monitor_counts_constructive": c, "monitor_counts_destructive": dd, "visibility": v,
            "phase_error_pct": None if v is None else 100 * (1 - v) / 2}


def dps_analysis(tags, sent, meta, a):
    slot_ps = meta["slot_ns"] * 1000
    n = meta["slots"]
    steps = sent.master_step.to_numpy()
    res = {}
    total = errors = 0
    both = tags[tags.channel.isin([a.mon_c, a.mon_d])]
    off = a.offset_ps if a.offset_ps is not None else find_offset(both.time_ps.to_numpy(), slot_ps, n, sent, a.window_ps)
    for ch, port_bit in ((a.mon_c, 0), (a.mon_d, 1)):
        t = tags[tags.channel == ch].time_ps.to_numpy()
        slot, within = fold(t, off, slot_ps, n)
        slot = slot[within < a.window_ps]
        sent_bit = (steps[(slot - 1) % n] > 0.5).astype(int)  # step before pulse k sets its phase difference
        errors += int(np.sum(sent_bit != port_bit))
        total += len(slot)
    res.update({"offset_ps": off, "bits_compared": total, "dps_qber_pct": 100 * errors / total if total else None})
    return res


def synth(protocol, out_dir: Path, n_slots=64, slot_ns=50.0, seconds=0.05, mu=0.2, eta=0.05, dark_Hz=100,
          visibility=0.95, seed=1):
    """Write a fake pattern folder and tags.csv with known QBER, for testing."""
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    if protocol == "cow":
        for k in range(n_slots // 2):
            b = rng.integers(0, 2)
            occ = (1, 0) if b == 0 else (0, 1)
            for j in (0, 1):
                rows.append({"slot": 2 * k + j, "slave_pulse": occ[j], "master_step": 0.0, "bit_index": k, "symbol": b})
    else:
        for k in range(n_slots):
            b = rng.integers(0, 2)
            rows.append({"slot": k, "slave_pulse": 1, "master_step": float(b), "bit_index": k, "symbol": b})
    sent = pd.DataFrame(rows)
    sent.to_csv(out_dir / "sent.csv", index=False)
    (out_dir / "meta.json").write_text(json.dumps({"protocol": protocol, "slots": n_slots, "slot_ns": slot_ns}))
    slot_ps = slot_ns * 1000
    n_periods = int(seconds / (n_slots * slot_ns * 1e-9))
    tags = []
    p_click = 1 - np.exp(-mu * eta)
    offset = 12_345.0
    for per in range(n_periods):
        base = offset + per * n_slots * slot_ps
        for k in range(n_slots):
            if rows[k]["slave_pulse"] and rng.random() < p_click:
                t = base + k * slot_ps + rng.normal(150, 50)
                if protocol == "cow":
                    tags.append((1, t))
                else:
                    want = int(rows[(k - 1) % n_slots]["master_step"] > 0.5)
                    port = want if rng.random() < (1 + visibility) / 2 else 1 - want
                    tags.append((2 + port, t))
    total_time_ps = n_periods * n_slots * slot_ps
    for ch in ((1,) if protocol == "cow" else (2, 3)):
        nd = rng.poisson(dark_Hz * total_time_ps * 1e-12)
        tags += [(ch, x) for x in rng.uniform(0, total_time_ps, nd)]
    if protocol == "cow":  # monitoring line: visibility-limited counts
        nm = 4000
        c = rng.binomial(nm, (1 + visibility) / 2)
        tags += [(2, x) for x in rng.uniform(0, total_time_ps, c)] + [(3, x) for x in rng.uniform(0, total_time_ps, nm - c)]
    df = pd.DataFrame(tags, columns=["channel", "time_ps"]).sort_values("time_ps")
    df.to_csv(out_dir / "tags.csv", index=False)
    return out_dir / "tags.csv"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tags", nargs="?", type=Path)
    p.add_argument("--pattern", type=Path, help="folder from qkd_patterns.py (sent.csv + meta.json)")
    p.add_argument("--data-ch", type=int, default=1)
    p.add_argument("--mon-c", type=int, default=2)
    p.add_argument("--mon-d", type=int, default=3)
    p.add_argument("--offset-ps", type=float, default=None)
    p.add_argument("--window-ps", type=float, default=1000.0, help="detection window after each slot start")
    p.add_argument("--demo", choices=["cow", "dps"])
    a = p.parse_args()
    if a.demo:
        folder = DATA_ROOT / "demo_timetags" / a.demo
        a.tags = synth(a.demo, folder)
        a.pattern = folder
    if not a.tags or not a.pattern:
        p.error("need a tags file and --pattern (or --demo)")
    meta = json.loads((a.pattern / "meta.json").read_text())
    sent = pd.read_csv(a.pattern / "sent.csv", dtype={"symbol": str})
    tags = pd.read_csv(a.tags)
    if meta["protocol"] == "cow":
        res = cow_analysis(tags, sent, meta, a)
    elif meta["protocol"] == "dps":
        res = dps_analysis(tags, sent, meta, a)
    else:
        _sys.exit("BB84 analysis needs Bob's basis choices; not implemented yet.")
    out = a.tags.parent / "qber_results.json"
    out.write_text(json.dumps(res, indent=2))
    for k, v in res.items():
        print(f"{k:32s} {v:.4g}" if isinstance(v, float) else f"{k:32s} {v}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
