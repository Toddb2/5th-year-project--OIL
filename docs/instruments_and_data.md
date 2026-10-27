# Instruments, and how their data reaches the laptop

Every instrument the scripts talk to connects to the laptop over **USB** (or LAN for the AWG and scope) and is driven through one of two software layers:

- **Thorlabs Kinesis** (Windows): the KLD101 laser drivers and TTC001 TEC controllers. The scripts call the Kinesis DLL directly, so the Kinesis *app* must be **closed** while a script runs (only one program can hold the USB connection).
- **VISA** (NI-VISA on Windows, or `pyvisa-py` elsewhere): the PM100D power meter, the AWG-5064 and the Tek scope, using text (SCPI) commands.

If a connection fails, every measurement script has a fallback: `--mode manual-driver` (you set the current, the script still reads the meter) or `--mode manual` (you type the readings in). A session is never lost to a driver problem.

## By stage

| Instrument | Stage | Role | Connection | Software | How data is recorded |
|---|---|---|---|---|---|
| Thorlabs **KLD101** K-Cube laser driver (×2) | 1–4 | Laser current (0–230 mA); reads back current, voltage, monitor photodiode | Mini-USB on the K-Cube; powered by its KPS201 supply | Kinesis (DLL via `ctypes`) | Script sets and reads it at every point |
| Thorlabs **TTC001** TEC controller (×2) | 1–4 | Holds each laser's temperature (10 kΩ thermistor) | USB; powered by TPS002 | Kinesis app or front panel | Set by hand; the set point is typed into each run (`--temp`) |
| **PM100D** + silicon sensor (S120C, ≤ 50 mW) | 1, 2 | Absolute optical power at 852 nm | USB | VISA (run the *Power Meter Driver Switcher* → NI-VISA if it isn't seen) | Script reads `MEAS:POW?` at every point |
| **OSA** (lab's, ≤ 0.05 nm resolution at 852 nm) | 1, 2 | Wavelength, FP modes, SMSR, locking | Usually export to USB stick (CSV) | — | Export traces as CSV; `osa_spectrum.py` / `locking_map.py` read them |
| Thorlabs **CCS** spectrometer (~0.5 nm) | 1 | Coarse wavelength only | USB | ThorSpectra (export CSV) | Too coarse for FP modes or SMSR |
| **V800PA** VOA + driver | 2 | Sets injection power (0–5 V control) | BNC control input | AWG CH3 in DC mode (High-Z) or a 5 V-limited supply | `voa_calibration.py` records V against power |
| **AWG-5064** (Active Technologies) | 3, 4 | Slave gain-switching pulses (CH1), master phase steps (CH2), marker for scope/tagger | LAN or USB; also loads waveform files from a USB stick | VISA (T3AWG6K commands) | `awg_oil_patterns.py` sets it; waveform files from `make_awg_files.py` / `qkd_patterns.py` |
| **ZFBT-6G-FT+** bias tee (×1–2) | 3, 4 | Adds AWG pulses to the DC laser current (≤ 500 mA DC) | SMA | — | — |
| **DET08CFC** fast photodiode (~5 GHz) + VOA850 | 3 | Pulse shapes and timing | FC/PC into the photodiode, SMA to scope | — | — |
| **Tektronix 4 Series MSO** | 3 | Pulse width, jitter, beat notes | USB or LAN | VISA | `scope_capture.py` saves every shot (`.npz`) and the analysis |
| Si SPADs + time tagger + delay-line interferometer (to borrow) | 4 | Single-photon detection, QBER, visibility | USB | Tagger's own software → export CSV (`channel,time_ps`) | `timetag_qber.py` |
| Multimeter | 1 | One-point check of the driver's voltage reading | — | — | Typed in |

## First-time laptop setup (Windows)

1. Install 64-bit **Python 3.11+**, **Thorlabs Kinesis**, and **NI-VISA**.
2. Clone the repo, then in its folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Put the KLD101 serial number (on the K-Cube, starts with 98) into `config/bench.toml`, and the sensor's maximum power.
4. With every laser **off**: `python 01_characterisation/check_instruments.py`. It should print the meter's ID and sensor, and the KLD101's status bits, polarity and current limit.
5. Practise with no hardware: add `--mode sim` to any script.

## Where data goes

`data/<date>/<what>_<kind>_<temp>C_<time>/`, one folder per run, containing the raw CSV (written point by point, so a stopped run keeps its data), `meta.json` (settings, instruments, code version, your `--note`) and the plots and fitted results. Commit the data you want to keep alongside the code that produced it.
