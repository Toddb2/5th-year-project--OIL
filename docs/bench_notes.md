# Bench notes: current state of the setup

A running record of how the bench is actually wired and set, what has been checked, and what
went wrong and why. Read this first before helping at the bench. Update it after each session.

*Last updated: 3 Nov 2026*

## Kit and serial numbers

| Item | Serial / setting | Notes |
|---|---|---|
| Master laser | Thorlabs DBR852PN, 14-pin butterfly, Type 1 | Threshold ~50 mA, ~0.09 W/A |
| Laser driver (master) | KLD101 **98251513** | Second KLD101: 98251629 (spare / later). Max 230 mA |
| TEC controller | TTC001 **87814309** | 20 kΩ thermistor range |
| Power meter | PM100D P0022425 with an **S130C** (Si, 400–1100 nm), slider on **500 mW** | Needs NI-VISA installed; then it appears as `USB0::0x1313::0x8078::P0022425::INSTR`. The S154C (InGaAs, 3 mW max) is the spare head: too small for the DBR above ~80 mA |
| Slave laser | FPL852P | Not used yet: needs a ≥ 1 A driver |
| Spectrometer | Thorlabs CCS175/M **M00766231** (500–1000 nm, SMA input) | Not an OSA: ~0.6–1 nm resolution. Good for the DBR peak and its tuning (peak fit to a few pm); can't resolve FP modes or SMSR. Needs ThorSpectra (installs TLCCS_64.dll); close it before scripts. Set `[spectrometer] control = "ccs"` |

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

### 3 Nov 2026: TEC diagnostic

| Phase | Result |
|---|---|
| A TEC off | 21.28 °C, no drift |
| B heat (set 24.28) | rose 2.16 °C, but mean current ≈ 0 mA and 1.9 °C swing |
| C cool (set 22.91) | fell 2.38 °C, 3.8 °C swing |
| D hold 25 °C | **oscillating 3.8 °C peak-to-peak, period ~2 s** |

The TEC heats and cools (wiring and polarity fine), but the loop is in a limit cycle: the current flips between ±490 mA every second or so. The TEC cold plate is small, so it can swing that fast. Fix: lower gains. `01_characterisation/tec_tune.py` reads the gains actually on the TTC001, tries gentler sets after a 1 °C step, keeps the best, and prints it for Kinesis (Current **and** Startup tabs, then Save).

### 3 Nov 2026: tuning, first stage 1 results, and what the logs show

- `tec_tune.py`: every gain set from P 15/I 4/D 60 down to P 1/I 0.5/D 0 swung the same ~3.7 °C, current pinned near ±490 mA. Gains make no difference, so it isn't a tuning problem.
- `tune_log.csv` (4 readings a second): the reading **jumps 2.4 °C in a single 0.25 s sample, exactly when the TEC current changes sign**, cycling 25.4 → 26.4 → 24.0 → 23.0 °C in step with the current (−420, −490, +410, +490 mA). A real temperature can't move that fast. **The TEC current is getting into the thermistor reading**: about −3.5 °C per amp, which is roughly 0.3 Ω shared between the thermistor return and the TEC current path (solder bridge, link, or a shared ground/wire on the PCB). The false reading drives the current into a bang-bang cycle.
- The laser itself does follow the cycle a little: in the 150 mA stability run the strongest power ripple is at exactly **2.0 s**, about 0.7 % peak-to-peak after warm-up, so ~1 °C of real swing rather than the 3.7 °C reported.
- **Fix:** with everything unplugged, thermistor pins 3/4 must be open circuit to TEC pins 5/13 at every stage (TTC001 end, chip plug, PCB). Give the thermistor its own two wires all the way back.
- **First stage 1 results (25 °C, TEC still cycling):** threshold **41.0 mA** (fit) / 42.0 mA (kink), slope **0.126 W/A**, **20.0 mW at 200 mA**, R_s **2.93 Ω**, V_0 1.16 V, peak wall-plug efficiency 5.8 %. Stability 0.16 % rms after the first minute, warm-up drift +0.9 % over the first ~40 s. Results in `results/characterisation/2026-11-03_DBR852PN/`. Repeat once the TEC holds.

- Pin check after the above: 3–5, 3–13, 4–5 and 4–13 all **open (OL)** at every stage. So there is no resistive short between the thermistor and the TEC wiring.
- Next test: `01_characterisation/tec_wavelength_check.py` uses the laser wavelength (~0.06 nm/°C on the CCS175) as a second thermometer while the TEC cycles, to tell a real temperature swing from a corrupted reading.
- `check_instruments.py` failed with everything still unplugged from the pin checks (PM100D missing, KLD101 power-supply bit off, TTC001 reading 0): reconnect the cables, the K-Cube power supplies and the meter's USB before scripts.

- `check_instruments.py` found the CCS but not the PM100D, although NI VISA Interactive Control listed both. `[power_meter] resource` is now set to `USB0::0x1313::0x8078::P0022425::INSTR` so the meter is opened directly, and auto-detect also tries an explicit USB query.
- **Stage 1 while the TEC cycles:** `[tec] settle = "mean"` in `config/bench.toml` waits for the 20 s mean of the reading to sit within 0.2 °C of the target instead of every reading within 0.05 °C. The runner logs the swing at each temperature. Results taken this way are **provisional**; set `settle = "strict"` and repeat once the TEC holds. How much the laser itself swings comes from `tec_wavelength_check.py`.

- First `tec_wavelength_check.py` (15:53) ran with the fibre still on the power meter: only 5 readings (the CCS kept lengthening its exposure looking for light) and no usable wavelength. **But the thermistor read 32.3 °C with the TEC at full cooling (−490 mA), set point 25 °C, laser at 150 mA.** Even allowing ~1.7 °C of pickup, the laser was ~30 °C and the TEC couldn't pull it down. Suspect the laser/PCB came off its heatsink during the pin checks. The script now stops on > set point + 5 °C, and the CCS exposure is capped at 0.5 s with a clear "no light" error.
- PM100D still not found by Python (`VI_ERROR_RSRC_NFOUND` at its known address) while NI VISA Interactive Control lists it. Started after ThorSpectra was installed, so pyvisa may be using a different VISA library: `check_instruments.py` now prints which, and `[power_meter] visa_library` can point it at NI's.

- **16:10, what the TEC is actually doing.** After the 150 mA run, with the laser off, the TTC001 still sat at **28.8 °C at full cooling (−490 mA)**. Switching the TEC **off** (diagnostic phase A) dropped it to 23.4 °C at −2 °C/min. So steady "cooling" left the laser *hotter* than no TEC at all. The diagnostic again cycled ~3.8 °C at ~2 s in B, C and D.
  - **Explanation that fits everything so far.** The reading carries an offset of about −3.5 °C per amp of TEC current (cooling at −0.49 A reads ~1.7 °C hot; heating reads ~1.7 °C cold). The loop then behaves as a relay with ~3.4 °C of hysteresis: once it cools, the reading jumps up, so it keeps cooling; once it heats, the reading jumps down, so it keeps heating. That gives the 3.4–3.8 °C jumps at every current reversal, and gains make no difference (seen in `tec_tune.py`).
  - **Why it latched hot.** With the base not heatsinked, full cooling dumps ~0.4 W of TEC heat plus the laser's heat into the mount. The true temperature stays near 27 °C (30 °C with the laser on). That never gets below set − 1.7 °C, so the current never flips back.
  - **Workaround until the new PCBs:**
    - In Kinesis, lower the TTC001 current limit from 500 to **200 mA** (Current and Startup tabs, Save). The pickup offset scales with current, so it shrinks to ~0.7 °C, and the unsinked base gets less heat.
    - Use set points above room temperature so the TEC mostly heats. `config/campaign.toml` now uses **25, 28, 31 °C**.
    - Keep `[tec] settle = "mean"`.
- Spectrometer straight on the fibre (no attenuation) saturates even at its 10 µs minimum exposure, as expected at 15 mW.
- The VOAs are on a piezo controller, not the AWG. Model numbers still to note. **Check the VOA's maximum control voltage before driving it from a piezo controller**: those output up to 75–150 V.
- Scripts run with VS Code's Run button (Code Runner) get no arguments and can't take typed input. Run them from the terminal.

#### If the reading is pickup

1. **Does it scale with TEC current?** In Kinesis lower the TTC001 current limit from 500 to 200 mA (Current and Startup tabs, Save) and re-run `tec_wavelength_check.py`. Electrical pickup shrinks in proportion (~3.7 → ~1.5 °C); a real thermal swing changes shape instead.
2. **Separate the wiring.** Thermistor pair (3/4) as its own twisted pair, routed away from the TEC pair (5/13), also twisted. Keep both short.
3. **PCB.** Look for the thermistor return sharing a trace, via or ground pour with TEC− or TEC+, or running alongside the TEC traces. Cut and rewire if so.
4. **Ground loop.** With everything unplugged, check the thermistor pins (3/4 on the 15-pin) are open to the laser-driver 9-pin pins 3 and 8 and to the butterfly case/mount.
- CCS175 spectrometer available. `wavelength_log.py --ccs` reads the peak automatically and saves each spectrum; `check_instruments.py --ccs` takes one test scan. The tuning steps of `run_experiment.py` use it when `[spectrometer] control = "ccs"`.

## FP slave (FPL852P) before the 1 A driver

Spec: threshold 240–300 mA, 0.51 W/A, 280–320 mW at 900–1000 mA, 14-pin butterfly Type 1 (same pinout as the DBR, so the same cables), 10 kΩ thermistor, monitor PD, PM fibre FC/APC. On the 230 mA KLD101 it stays below threshold: I–V, spontaneous emission and the FP mode comb only (`01_characterisation/fp_subthreshold.py`). Its `max_current_mA` in `config/bench.toml` is 0 (blocked) until Todd sets it to 200 by hand for this.

## Plan from here

1. **Today:** pull; S130C on the meter (slider 500 mW); `check_instruments.py`; TEC settled at 25 °C; first light `li_sweep.py --temp 25 --stop 80 --zero`.
2. **Stage 1:** `run_experiment.py --stages characterisation` (L–I–V at 20/25/30 °C, T0, 10 min stability; OSA tuning when booked; skip with `s` otherwise). Results in `results/characterisation/`; commit them.
3. **Tuning (CCS175 now, OSA later for SMSR/FP modes):** wavelength vs current and temperature (tuning map, mode hops). Put the measured pm/mA into `[injection] master_tuning_pm_per_mA`.
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
