# Running one laser: DBR852PN on the KLD101

The KLD101 can only reach **230 mA**, so the laser for today is the **DBR852PN (master)**. That gets you to about 16 mW. The FPL852P (slave) needs about 1 A and waits for a bigger driver; the scripts refuse to run it on the KLD101.

## 1. Cables and meter checks (everything unpowered)

| Link | Cable | Check with the meter first |
|---|---|---|
| KLD101 LD output (DB9) → mount LASER | Straight DB9 M–F if the mount uses the Thorlabs pinout. For the Arroyo mount use the E1 adapter: KLD101 pin 8 → Arroyo 8 + 9 (anode), KLD101 pin 3 → Arroyo 4 + 5 (cathode) | Diode test on the KLD101-side plug, red on pin 8, black on pin 3: about 1.2–1.6 V one way, open the other way. **Pins 1 and 5 linked** in the KLD101-side plug (interlock) |
| TTC001 TEC output (DB15) → mount TEC | CAB420-15 or straight DB15; E2 adapter for the Arroyo | At the TTC001 end: pins 3–4 about **10 kΩ** (thermistor), pins 5–13 a **few ohms** (TEC), nothing between the two groups |
| Laser fibre → power sensor | Clean the FC/APC end; S120-FC adapter on the sensor | Sensor rating covers ~16 mW (S120C = 50 mW is fine; an S154C (3 mW) is not, without an attenuator) |

If the PCB mounts from the group are used instead of the Arroyo, ask the designer whether the D-sub pinout is Thorlabs Type 1 (anode on pin 8 for cathode-grounded drive). Don't assume.

## 2. TTC001 (TEC) settings: switch on first

| Setting | Value |
|---|---|
| Sensor | Thermistor, 20 kΩ range |
| Set point | **10.00 kΩ** (≈ 25 °C for a 10 kΩ NTC) |
| TEC current limit | **0.5 A** (the DBR draws about 0.23 A) |
| Loop | Default PID to start |

Enable it and watch the reading move **towards** 10.00 kΩ and settle within a minute or two. If it runs **away** from the set point, switch off at once: TEC+ and TEC− are swapped. If the TEC current sits at the limit, the heat-sinking is poor.

## 3. KLD101 (laser driver) settings: output OFF while you set these

| Setting | Value | Why |
|---|---|---|
| Polarity | **Cathode grounded (CG)** | Matches the wiring above; wrong polarity reverse-biases the laser |
| Mode | **Constant current** (open loop) | Constant power needs a calibrated monitor photodiode |
| Current limit (ILIM) | **200 mA** for the first session; 230 mA later | Hardware cap that protects the laser even if a script or a knob goes wrong. Expect ~13.5 mW at 200 mA |
| Set point | **0 mA** before enabling | |
| Ramp-up | Ramped (soft start) | No current step at switch-on |
| External SMA modulation input | Disabled, nothing connected | The bias tee comes later |

Close the Kinesis app before running the scripts: it holds the USB connection.

## 4. Power meter (PM100D)

Wavelength **852 nm**, units W, autorange. Zero it with the laser off (`--zero` does this).

## 5. Order

**On:** goggles on → TEC on and stable → driver enabled at 0 mA → ramp up.
**Off:** ramp to 0 → driver off → TEC off.

## What to expect, and when to stop

- Nothing (nW) below ~50 mA, then a sharp kink and a straight line at about **0.09 mW per mA**.
- About **4.5 mW at 100 mA**, **13.5 mW at 200 mA**.
- **Stop** if there's no power by 70 mA (check fibre and polarity), if the measured current is below the set point (open circuit or compliance), or if the TEC can't hold temperature.

## What each measurement tells you

| Measurement | Script | Gives you | Why it matters for OIL |
|---|---|---|---|
| L–I–V | `01_characterisation/li_sweep.py` | Threshold, slope efficiency, forward voltage, series resistance, wall-plug efficiency | Baseline health check against the spec sheet; sets the injection power range |
| Monitor photodiode vs power | `01_characterisation/li_sweep.py` (pd column) | Photodiode responsivity | Lets you monitor master power later without breaking the fibre |
| L–I at 20, 25, 30 °C | `01_characterisation/li_sweep.py` + `compare_temperatures.py` | Threshold vs temperature, T0 | How sensitive the laser is to temperature drift |
| Wavelength vs current and temperature | `wavelength_log.py` (OSA, spectrometer or wavemeter) | pm/mA, nm/°C, mode hops | **The key one for injection locking**: this map is how you tune the master onto a slave FP mode |
| Power over 10–30 min | `power_stability.py` | Warm-up drift and stability | Shows how long to wait before locking experiments |
| Spectrum at a few currents | OSA, saved by hand | Side-mode suppression ratio | Confirms the master is single-mode where you'll use it |
