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
| Power meter | PM100D P0022425, sensor **S154C** (InGaAs, 800–1700 nm, **3 mW max**) | Needs NI-VISA installed; then it appears as `USB0::0x1313::0x8078::P0022425::INSTR` |
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
- After the TEC works: `check_instruments.py`, then a first sweep with `li_sweep.py --temp 25 --stop 80 --zero`, then `run_experiment.py --stages characterisation`.

## Expected values (DBR852PN, 25 °C)

| Quantity | Expected |
|---|---|
| Threshold | ~50 mA |
| Power at 80 / 100 / 200 mA | ~2.7 / ~4.5 / ~13.5 mW |
| Forward voltage | ~1.5–2 V |
| Thermistor (10 kΩ NTC, β ≈ 3950 K) | 12.5 kΩ = 20 °C; 10.0 kΩ = 25 °C; 8.0 kΩ = 30 °C |
