# Bench notes: current state of the setup

A running record of how the bench is actually wired and set, what has been checked, and what
went wrong and why. Read this first before helping at the bench. Update it after each session.

*Last updated: 29 Oct 2026*

## Kit and serial numbers

| Item | Serial / setting | Notes |
|---|---|---|
| Master laser | Thorlabs DBR852PN, 14-pin butterfly, Type 1 | Threshold ~50 mA, ~0.09 W/A |
| Laser driver (master) | KLD101 **98251513** | Second KLD101: 98251629 (spare / later). Max 230 mA |
| TEC controller | TTC001 **87814309** | 20 kΩ thermistor range |
| Power meter | PM100D P0022425 with an **S130C** (Si, 400–1100 nm), slider on **500 mW** | Needs NI-VISA installed; then it appears as `USB0::0x1313::0x8078::P0022425::INSTR`. The S154C (InGaAs, 3 mW max) is the spare head: too small for the DBR above ~80 mA |
| Slave laser | FPL852P | Not used yet: needs a ≥ 1 A driver |

Serials are in `config/bench.toml`. The "EEPROM serial number mismatch" warning Kinesis shows for the TTC001 is harmless.

## Wiring

All cables are hand-made from hookup wire on solder-cup D-subs. There are two layers.

**1. Chip-side plugs**, wired to the laser (via the PCB):

| Plug | Cup | Laser (butterfly pin) |
|---|---|---|
| 9-pin | 8 | 10, laser anode |
| 9-pin | 3 | 11, laser cathode |
| 9-pin | 4 | 3, photodiode anode |
| 9-pin | 2 | 4, photodiode cathode |
| 9-pin | 1–5 | Linked inside the plug (interlock) |
| 15-pin | 5, 6, 7 | Linked, then to 1 (TEC +) |
| 15-pin | 13, 14, 15 | Linked, then to 14 (TEC −) |
| 15-pin | 3 and 4 | 5 and 2, thermistor (either way round) |

**2. Extension cables**, straight-through (pin N to pin N, going by the moulded numbers):

| Cable | Pins carried |
|---|---|
| 9-pin (KLD101 → chip plug) | 1, 2, 3, 4, 5, 8 |
| 15-pin (TTC001 → chip plug) | 3, 4, 5, 13 |

Pinouts used:
- **KLD101 LD output** (manual, App. A.2): 1 interlock, 2 PD cathode, 3 LD ground, 4 PD anode, 5 interlock return, 7 LD cathode (anode-grounded only, keep empty), 8 LD anode (cathode-grounded).
- **TTC001 output**: 3/4 thermistor, 5–7 TEC +, 13–15 TEC −, 10/11 AD592 (unused).
- **Butterfly Type 1**: 1 TEC +, 2 and 5 thermistor, 3 PD anode, 4 PD cathode, 10 LD anode, 11 LD cathode, 13 case (unconnected), 14 TEC −.

## Instrument settings

**KLD101** (Kinesis):
- Constant current, cathode grounded.
- Max Laser Current **200 mA** (done 29 Oct).
- TIA 10 mA.
- With the cables in, Safety Key and Interlock both show green and Open Circuit is off.

**TTC001** (Kinesis):
- Sensor **20 kOhm Thermistor**.
- Current limit 500 mA.
- Target 10.00 kΩ (about 25 °C).
- Kinesis pushes its **Startup** settings to the device on connect. They were on "Transducer", which caused the "ErrOr" display. Set the Startup tab to 20 kOhm Thermistor and press **Save** (custom settings).
- The Python driver (`oil852/instruments/tec.py`) sets the sensor type itself on connect.

**Kinesis and the Thorlabs power meter app must be closed before running any script**: each holds its instrument's USB connection.

## Session log

### 29 Oct 2026: bring-up

- TTC001 "ErrOr" when enabling: the sensor type had been reset to Transducer by the Kinesis startup settings. Fixed by selecting 20 kΩ thermistor; it now reads ~12.4 kΩ at room temperature (~20 °C).
- TEC does not change the temperature when enabled. The reading only drifts back towards room temperature, the same with both TEC polarities, so no TEC current is reaching the laser.
  - At the laser, butterfly pins 1–14 read ~1.5 Ω, rising slowly on the meter. That is normal for a TEC on an ohmmeter (the Seebeck effect), so the TEC itself is fine.
  - Links on the chip-side 15-pin are good: 5–6–7 and 13–14–15 all read ≤ 0.1 Ω.
  - The extension carries only pins 3, 4, 5 and 13, which is correct: the chip-side plug does the linking.
  - **Next:** measure pins 5–13 at the TTC001 end of the extension (whole chain, laser connected). It should read ~1.5 Ω. Open means the break is in the extension or at the chip-plug cups. Then, enabled, check the TTC001 TEC current reads near the limit.
- **Found the TEC break:** the extension's chip-side end had the TEC− wire on cup 12 instead of 13 (pin 12 is unconnected on the chip plug). Moved to 13.
- First `check_instruments.py` run on the laptop:
  - `No module named 'pyvisa'`: the Python packages weren't installed. Fix: `python -m pip install -r requirements.txt`.
  - `LD_GetMaxCurrentDigPot not found`: this Kinesis version doesn't export it. The driver now treats it and other extras as optional; `01_characterisation/dll_functions.py` lists what the installed DLLs provide.
  - TTC001 read 0.00 kOhm right after connecting (Kinesis showed 12.4 kΩ). The driver now waits up to 5 s for the first reading and no longer applies Kinesis' stored startup settings. Kinesis must be closed.
- NI-VISA was not installed; after installing it the PM100D is seen over VISA and `check_instruments.py` passes for all three instruments. TEC reached 25 °C (TEC current ±490 mA while settling).
- The sensor is an S154C, rated to 3 mW. The DBR reaches ~13.5 mW at 200 mA, so sweeps stop themselves near 80 mA unless a fibre attenuator is fitted and `[power_meter] attenuation_dB` is set. Known sensor heads are now recognised automatically.
- `li_sweep.py` stopped with "polarity is anode_grounded": the KLD101 status bits were read before the cube had reported them (all zero). The driver now waits for real status bits.
- Stage 1 results: `01_characterisation/make_figures.py` (also run automatically at the end of stage 1 by `run_experiment.py`) writes PNG + PDF figures and a results table to `results/characterisation/`.
- Swapped the S154C for an S130C (slider on 500 mW): no attenuator needed for the full 200 mA sweep.
- KLD101 polarity flipped to anode grounded again after Kinesis was opened (its Startup settings). Set Cathode grounded on both the Current and Startup tabs and Save.
- First sweep (`li_sweep.py --stop 80`) stopped at 10 mA: the KLD101 current readback stayed at 0.00 mA while its voltage rose 0.33 → 1.03 V (2–10 mA) and the power went from 0 to ~0.1 µW. Either the readback is dead in this Kinesis version or current isn't reaching the laser. Test in Kinesis: enable at 10 mA, then 60 mA, and compare Kinesis' current display with the PM100D (expect ~0.9 mW at 60 mA). The sweep now carries on when the readback is 0 but the voltage and status are normal, and stops instead on V > 2.6 V or no light above 75 mA.
- **Kinesis test (29 Oct, 17:47): the laser works.** Kinesis showed 10.00 mA at 1.08 V; the PM100D read 0.125 µW at 10 mA and ~2.36 mW at 60 mA. So only the script's current readback fails, and the threshold looks lower than the 50 mA spec guess. The driver now also calls `LD_RequestStatus` before reading; if the readback still says 0, the sweep logs the set point.
- Kinesis shows no photodiode current ("-.- µA"): either the DBR852PN has no monitor photodiode on pins 3/4 or those wires aren't connected. Not needed in constant-current mode.
- **First L–I (29 Oct 17:53, 25 °C, 0–80 mA):** threshold **41.5 mA** (fit) / 40.0 mA (kink), slope **0.127 W/A**, 4.91 mW at 80 mA, R_s ≈ 3.5 Ω. The current readback works now (it reads the set values). Run `data/2026-10-29/DBR852PN_LIV_25C_175353`.
- First `run_experiment.py --stages characterisation` stopped at the 20 °C step with a false "running away" alarm. The TEC was still swinging (21.5 ↔ 26.3 °C) and the overshoot looked like divergence. Now: set-point ramping (3 °C/min), the alarm only trips on 2 min of steady divergence or outside the safe range, and a TEC failure gives retry/skip/quit instead of a crash.
- Second stage 1 attempt (18:05): the TEC had been left off by the false alarm (21.3 °C, 0 mA). Asked for 20 °C it drove −490 mA (cooling) but the laser rose to ~25.8 °C; below the set point it drives +490 mA (heating), so the sign is right. The laser may not be properly on the heatsink block. Run `01_characterisation/tec_diagnostic.py` (TEC off / heat / cool / hold, logged every second, with a verdict per phase) to tell heatsinking, wiring and loop tuning apart.
- TEC oscillating between ~23 and ~27 °C with the current pinned at ±490 mA: the loop gains (P 15, I 4, D 60) were too high for this mount. Lowered (P ~5, I ~1) on both the Current and Startup tabs and saved to the device; check it settles.
- After the TEC works: `check_instruments.py`, then a first sweep with `li_sweep.py --temp 25 --stop 80 --zero`, then `run_experiment.py --stages characterisation`.

## Plan from here

1. **Today:** pull; S130C on the meter (slider 500 mW); `check_instruments.py`; TEC settled at 25 °C; first light `li_sweep.py --temp 25 --stop 80 --zero`.
2. **Stage 1:** `run_experiment.py --stages characterisation` (L–I–V at 20/25/30 °C, T0, 10 min stability; OSA tuning when booked; skip with `s` otherwise). Results in `results/characterisation/`; commit them.
3. **OSA session:** wavelength vs current and temperature (tuning map, mode hops, SMSR). Put the measured pm/mA into `[injection] master_tuning_pm_per_mA`.
4. **Passive parts with the master as the source:** insertion loss and split ratios of the 99:1 couplers, circulator loss and isolation, PM fibre connectors. Then `voa_calibration.py`.
5. **AWG into the scope (50 Ω), no laser:** confirm the double-pulse and protocol patterns with `scope_capture.py`.
6. **Slave:** needs a ≥ 1 A driver (ask Ross). Characterise the FPL852P, then stage 2 locking maps, stage 3 gain switching, stage 4 QKD.
7. **Throughout:** write up methods and results as each stage closes.

## Expected values (DBR852PN, 25 °C)

| Quantity | Expected |
|---|---|
| Threshold | ~50 mA |
| Power at 80 / 100 / 200 mA | ~2.7 / ~4.5 / ~13.5 mW |
| Forward voltage | ~1.5–2 V |
| Thermistor (10 kΩ NTC, β ≈ 3950 K) | 12.5 kΩ = 20 °C; 10.0 kΩ = 25 °C; 8.0 kΩ = 30 °C |
