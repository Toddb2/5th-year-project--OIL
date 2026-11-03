# DBR852PN characterisation results

Made 03 Nov 2026 14:56 from 1 L–I–V run(s). Reference temperature 25 °C.

| Quantity | Spec sheet | Measured |
|---|---|---|
| Threshold (25 °C) | ~50 mA | 41.0 mA (fit), 42.0 mA (kink) |
| Slope efficiency | 0.09 W/A | 0.126 W/A |
| Power at 200 mA | ~13.5 mW | 20.0 mW |
| Series resistance | – | 2.93 Ω |
| T0 | – | needs two or more temperatures |
| Current tuning | ~2 pm/mA | not measured |
| Temperature tuning | ~0.06 nm/°C | not measured |
| Monitor photodiode | – | not read |
| Power stability | – | 0.263 % rms, 1.80 % peak-to-peak over 5 min |
| Stability after the first minute | – | 0.159 % rms, 0.69 % peak-to-peak, strongest ripple every 2.0 s; warm-up drift +0.87 % |

## Per temperature

| temperature_C | threshold_fit_mA | threshold_kink_mA | slope_W_per_A | fit_r2 | max_power_mW | current_at_max_mA | series_resistance_ohm | turn_on_V | wallplug_peak_pct | pd_uA_per_mW | attenuation_dB | sweep_ended |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 25.0 | 41.04 | 42.02 | 0.126 | 0.99998 | 20.003 | 200.0 | 2.93 | 1.163 | 5.77 | 0.0 | 0.0 | completed |

## Figures

- `fig_LI.png` / `fig_LI.pdf`
- `fig_dPdI.png` / `fig_dPdI.pdf`
- `fig_IV.png` / `fig_IV.pdf`
- `fig_stability.png` / `fig_stability.pdf`

Data runs used:

- `DBR852PN_LIV_25C_144640`