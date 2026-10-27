# Data

Each measurement makes `data/<date>/<what>_<kind>_<temp>C_<time>/` with the raw CSV (written point by point), `meta.json` (settings, instruments, code version, note) and the plots and fit results. Commit the runs you want to keep. Simulated runs (`--mode sim`) are labelled as such in their `meta.json`; don't commit those.
