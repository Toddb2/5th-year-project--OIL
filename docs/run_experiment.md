# Running the whole experiment: `run_experiment.py`

One command runs every stage in order: characterisation → injection locking → pulsed → QKD. It
sets the laser temperature on the TTC001, runs each sweep, changes the value (temperature, VOA
attenuation, slave current, bias) and runs again, analysing as it goes. When something has to be
done by hand it stops and tells you exactly what to do.

```bash
python run_experiment.py --mode sim      # rehearse the whole thing first (about 3 minutes)
python run_experiment.py --list          # see every step
python run_experiment.py                 # the real bench
```

What to sweep lives in [`config/campaign.toml`](../config/campaign.toml); instruments and safety
limits stay in [`config/bench.toml`](../config/bench.toml).

## Before a real run

1. **Close the Kinesis app and the Thorlabs power meter app.** Each holds its instrument's USB
   connection, and the scripts can't reach an instrument that is held. Use the apps to check things,
   then close them before you run anything.
2. Fill in `config/bench.toml`: the KLD101 serial under `[driver]`, the TTC001 serial under `[tec]`,
   and the thermistor `r25_kohm` and `beta_K` from the laser datasheet.
3. Run `python 01_characterisation/check_instruments.py`. It should report the power meter, the
   KLD101 (interlock OK, cathode grounded, constant current) and the TTC001 (about 10 kΩ at room
   temperature). The laser stays off.
4. Try the TEC on its own: `python 01_characterisation/set_temperature.py --to 25`. If the
   temperature runs away from the target, the script switches the TEC off. That means TEC+ and TEC−
   are swapped.

## What it does

| Stage | Steps | Done by hand |
|---|---|---|
| 1 Characterisation | L–I–V at each temperature → threshold vs T and T0 → power stability → wavelength vs current at each temperature | Fibre to the power meter, later to the OSA; type each OSA peak wavelength |
| 2 Injection locking | VOA calibration → OSA spectra → a locking map for every slave current × VOA attenuation → comparison with theory | Build the injection path; set the slave driver; export OSA traces or type locked y/n |
| 3 Pulsed | AWG double-pulse setup → check on the scope → pulse capture at each slave bias | Move cables to the bias tee; set each slave bias |
| 4 QKD | COW/DPS patterns → load on the AWG → QBER and visibility from time tags → key rate vs fibre length using the measured visibility | Copy the files to the AWG stick; record and export the time tags |

The master temperature is set automatically before every sweep that needs it, and the VOA is set
from its own calibration curve for each injection ratio. That happens automatically if
`[voa] control = "awg"`; otherwise the runner asks you to set the voltage. The measured master
tuning (pm/mA) from stage 1 is carried into the stage 2 locking maps.

## At each prompt

- **Enter**: done, carry on.
- **s**: skip this step.
- **q**: quit. Progress is kept.

**Ctrl+C** during a sweep ramps the laser down and switches it off. If a step fails, the runner
asks whether to retry, skip or quit.

## Output

Everything from one campaign goes in `data/campaigns/<date>_<time>_<name>/`:

```
campaign.toml, bench.toml   copies of the settings used
log.txt                     what happened, with times
state.json                  which steps are done (used by --resume)
data/                       every run folder: CSV, meta.json, plots
figures/                    summary plots across runs
report.html                 all figures and key numbers per stage; open in a browser
report.md, summary.json     the same as Markdown and as numbers for tables
```

## Carrying on, repeating, rebuilding

```bash
python run_experiment.py --resume data/campaigns/<folder>                    # carry on where it stopped
python run_experiment.py --resume data/campaigns/<folder> --redo c.liv.25C   # repeat one step
python run_experiment.py --resume data/campaigns/<folder> --redo l.map       # repeat every locking map
python run_experiment.py --stages characterisation                           # stage 1 only
python run_experiment.py --report data/campaigns/<folder>                    # rebuild the report
```

## Not automated yet

- **OSA.** It isn't controlled by the laptop yet, so you read the peak wavelength or export traces
  by hand. Give me the OSA model and it can be read over VISA like the power meter.
- **Slave driver.** It needs a driver that reaches at least 1 A, and that isn't on the bench yet.
  The runner asks you to set it.
- **Time tagger.** You export detections as `channel,time_ps` CSV. The analysis takes it from there.
- **AWG DC commands for the VOA.** These are in `[voa]` and have not been checked on the AWG-5064
  yet. Test them once with `voa_calibration.py --set 2.5 --voa awg` and a multimeter.
