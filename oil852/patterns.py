"""Drive patterns for the OIL transmitter and AWG waveform files.

Timing model: the slave is gain-switched once per time slot (pulse at the start of the slot).
The master gets short current steps in the gaps between slave pulses; a step changes the
master's optical phase, and through injection locking the phase of the next slave pulse.

- COW: master CW (no steps). Each logical bit uses two slots: bit 0 = pulse then empty,
  bit 1 = empty then pulse, decoy = pulse, pulse.
- DPS: slave pulses every slot. A master step before a pulse sets that pulse's phase relative
  to the previous one: level 0 = no step (phase 0), level 1 = step giving a pi phase shift.
- BB84 (phase / time-bin encoding with OIL): a symbol table maps each of the four states to a
  master step level. The default table matches the AWG bundle used on the bench so far
  (+Vm, deep drop below master threshold, -Vn, none). CONFIRM the mapping with your supervisor;
  it depends on the calibrated phase per volt.

AWG files: one sample per line in -1..+1, as loaded through the AWG-5064's Wave. List.
The instrument scales them with its High/Low settings. Keep files at 16384 samples or fewer.
"""

from __future__ import annotations

import numpy as np

MAX_SAMPLES = 16384

DEFAULT_BB84_LEVELS = {"Z0": 0.5, "Z1": -1.0, "X0": -0.25, "X1": 0.0}


def cow_slots(bits, decoy_fraction=0.1, rng=None):
    """Return (slave_slot_levels, labels). bits: iterable of 0/1."""
    rng = rng or np.random.default_rng()
    slots, labels = [], []
    for b in bits:
        if rng.random() < decoy_fraction:
            slots += [1, 1]
            labels.append("decoy")
        elif b == 0:
            slots += [1, 0]
            labels.append(0)
        else:
            slots += [0, 1]
            labels.append(1)
    return np.array(slots, float), labels


def dps_steps(bits):
    """Master step level before each slave pulse: 1 = pi phase step, 0 = none.
    Bob's DPS bit is the phase difference between neighbouring pulses, i.e. the step itself."""
    return np.asarray(bits, float)


def bb84_steps(symbols, levels=None):
    levels = levels or DEFAULT_BB84_LEVELS
    return np.array([levels[s] for s in symbols], float)


def random_bb84_symbols(n, rng=None):
    rng = rng or np.random.default_rng()
    return [rng.choice(["Z0", "Z1", "X0", "X1"]) for _ in range(n)]


def render(levels, samples_per_slot: int, start_frac: float, width_frac: float, edge_frac: float = 0.02):
    """Turn per-slot levels into a waveform: a flat-topped pulse of the given level in each slot."""
    levels = np.asarray(levels, float)
    n = len(levels) * samples_per_slot
    if n > MAX_SAMPLES:
        raise ValueError(f"{n} samples exceeds the AWG file limit of {MAX_SAMPLES}; use fewer slots or samples")
    y = np.zeros(n)
    e = max(1, int(edge_frac * samples_per_slot))
    w = max(2 * e + 1, int(width_frac * samples_per_slot))
    s0 = int(start_frac * samples_per_slot)
    ramp = np.linspace(0, 1, e, endpoint=False)
    for k, lv in enumerate(levels):
        if lv == 0:
            continue
        a = k * samples_per_slot + s0
        y[a:a + e] = lv * ramp
        y[a + e:a + w - e] = lv
        y[a + w - e:a + w] = lv * ramp[::-1]
    return y


def slave_waveform(slot_levels, samples_per_slot=1000, pulse_width_frac=0.2):
    """CH1: slave pulse at the start of each slot (level 1 = pulse, 0 = empty)."""
    return render(slot_levels, samples_per_slot, 0.0, pulse_width_frac)


def master_waveform(step_levels, samples_per_slot=1000, step_width_frac=0.1, start_frac=0.5):
    """CH2: master step placed in the gap after slave pulse k (from start_frac of the slot),
    so step k sets the phase of pulse k+1 relative to pulse k. The pattern wraps, so the
    last step sets the phase of the first pulse of the next repetition."""
    return render(step_levels, samples_per_slot, start_frac, step_width_frac)


def save_awg_file(path, y):
    y = np.asarray(y, float)
    peak = np.max(np.abs(y)) or 1.0
    np.savetxt(path, y / peak, fmt="%.5f")
    return peak
