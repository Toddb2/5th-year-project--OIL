# Stage 1: single-laser characterisation

Measure each laser on its own before any locking: power, voltage and monitor-photodiode current against drive current (L–I–V), how the threshold moves with temperature (T0), how the wavelength tunes with current and temperature, and how stable the output is.

**Read [../docs/bench_settings.md](../docs/bench_settings.md) first** (driver, TEC and meter settings, switch-on order).

| Script | Does | Example |
|---|---|---|
| `check_instruments.py` | Confirms the laptop sees the KLD101 and PM100D; laser stays off | `python 01_characterisation/check_instruments.py` |
| `li_sweep.py` | L–I–V sweep with fits for threshold, slope efficiency and series resistance | `python 01_characterisation/li_sweep.py --temp 25 --stop 200 --zero` |
| `compare_temperatures.py` | Threshold vs temperature and T0 from several sweeps | `python 01_characterisation/compare_temperatures.py data/<date>/DBR852PN_LIV_*` |
| `power_stability.py` | Power over time at a fixed current | `python 01_characterisation/power_stability.py --temp 25 --current 150 --minutes 20` |
| `wavelength_log.py` | Wavelength vs current/temperature from the OSA or wavemeter; tuning coefficients and mode hops | `python 01_characterisation/wavelength_log.py --temp 25 --currents 60:200:10 --file data/tuning_DBR852PN.csv` |
| `analyse_li.py` | Re-analyse saved or hand-typed L–I data | `python 01_characterisation/analyse_li.py data/<date>/DBR852PN_LIV_25C_*` |

Modes on every measuring script: `auto` (default), `manual-driver`, `manual`, `sim`.

**Expected for the DBR852PN** (spec sheet): threshold ~50 mA, slope ~0.09 W/A (≈ 13.5 mW at 200 mA), tuning ~2 pm/mA and ~0.06 nm/°C. The FPL852P (threshold 200–300 mA, 0.51 W/A, up to 900 mA) waits for a ≥ 1 A driver; the scripts refuse to run it on the KLD101.

![Example L–I–V from the simulated laser](../docs/img/example_liv_sim.png)
