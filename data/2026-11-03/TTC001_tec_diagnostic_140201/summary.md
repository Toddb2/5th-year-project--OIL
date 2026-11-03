# TEC diagnostic (completed)

| Phase | Set point (C) | Start (C) | End (C) | Change (C) | Rate (C/min) | Mean TEC (mA) | Last-2-min spread (C) | Verdict |
|---|---|---|---|---|---|---|---|---|
| A TEC off | off | 21.28 | 21.28 | +0.00 | -0.00 | +0 | 0.000 | ambient drift -0.00 C/min with the TEC off |
| B heat | 24.28 | 21.28 | 23.44 | +2.16 | +0.90 | -0 | 1.866 | HEATING WORKS: temperature rose with positive current |
| C cool | 22.91 | 24.91 | 22.53 | -2.38 | +0.04 | -7 | 3.832 | COOLING WORKS: temperature fell with negative current |
| D hold 25 C | 25.00 | 25.90 | 25.16 | -0.74 | +0.05 | -5 | 3.812 | OSCILLATING: 3.81 C peak-to-peak, period ~2 s. Lower the proportional and integral gains (and heatsink the laser). |
