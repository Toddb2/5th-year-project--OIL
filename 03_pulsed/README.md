# Stage 3: pulsed operation

Gain-switch the slave with short AWG pulses through the bias tee (on top of a DC bias just below threshold), lock it to the CW master, then add master phase steps between the slave pulses.

| Script | Does |
|---|---|
| `awg_oil_patterns.py dp` | CH1: 10 ns slave pulses every 50 ns. CH2: ± master steps (5 ns) centred in the gaps, one each per two slave pulses. The setup proven on the bench into 50 Ω |
| `awg_oil_patterns.py files [dps\|bb84]` | Same timing, CH1/CH2 played from waveform files on the AWG's USB stick |
| `awg_oil_patterns.py off` | Stop and switch outputs off |
| `make_awg_files.py` | Writes `ch1_slave_pulses.txt`, `ch2_master_dps.txt`, `ch2_master_bb84.txt` (+ README) for the USB stick |
| `scope_capture.py` | Grabs N single shots from the Tek scope and measures period, FWHM, timing jitter, amplitude spread and extinction |

Before anything goes to a laser:
1. Check every AWG level on the scope **into 50 Ω**. `config/bench.toml [awg]` caps the levels the scripts will set.
2. Slave DC bias on its driver, limit ≤ 450 mA while the bias tee is in circuit (bias tee rated 500 mA).
3. 20 dB attenuation in front of the fast photodiode.

Things to measure: pulse width and jitter against DC bias and pulse amplitude; how locking narrows the jitter; extinction between pulses (needed for COW).

![Simulated pulse train](../docs/img/sim_pulse_trace.png)
