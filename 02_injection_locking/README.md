# Stage 2: CW injection locking

Inject the DBR master into the FP slave through the circulator and find where, and how strongly, the slave locks.

Order of work:

1. **Calibrate the VOA** in the master path (power through it at 0–5 V control). This turns "VOA voltage" into "injection ratio".
   `python 02_injection_locking/voa_calibration.py --master-mA 150`
2. **Characterise the free-running slave on the OSA**: mode spacing and where its modes sit. Export traces as CSV.
   `python 02_injection_locking/osa_spectrum.py slave_free_400mA.csv`
3. **Locking map**: hold the slave current, step the master current in 1 mA steps through a slave mode, and record locked / not locked and the SMSR at each point (point the script at an OSA export, or type the result). Repeat at several VOA settings.
   `python 02_injection_locking/locking_map.py --temp 25 --slave-mA 400 --voa-dB 20 --currents 80:200:1`
4. **Compare with theory**: locking window against injection ratio, in GHz and in master mA, with the measured windows overlaid.
   `python 02_injection_locking/locking_theory.py --measured data/<date>/OIL_locking_map_*/summary.json`

What locking looks like: the FP comb (modes ~0.1 nm apart) collapses into one line at the master wavelength with side modes suppressed by > 30 dB.

Notes:
- The slave needs a ≥ 1 A driver, and its light must never pass through the VOA (rated 100 mW).
- At ~0.83 GHz per mA of master current, expect locking windows of only a few mA: use 1 mA steps or finer, and let the TECs settle.
- The CCS spectrometer (~0.5 nm) cannot resolve the FP modes; use the OSA.

![Simulated FP comb, free-running and locked](../docs/img/sim_spectra.png)
![Expected locking range](../docs/img/sim_locking_range.png)
