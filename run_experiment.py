"""Run the whole OIL experiment in one go: characterisation -> injection locking -> pulsed -> QKD.

It works through config/campaign.toml step by step: sets the laser temperature on the TTC001,
runs each sweep, changes the value, runs again, and analyses as it goes. When something has to be
done by hand (move a fibre, set the slave driver, export an OSA trace) it stops and tells you.
Everything from one campaign lands in data/campaigns/<date>_<time>_<name>/, ending with
report.html (all figures and key numbers) and summary.json.

  python run_experiment.py --mode sim                  # rehearse everything with simulated instruments
  python run_experiment.py --list                      # show the steps without running anything
  python run_experiment.py                             # real bench, every stage in campaign.toml
  python run_experiment.py --stages characterisation   # just stage 1 (also: locking, pulsed, qkd)
  python run_experiment.py --resume data/campaigns/2026-10-29_141500_oil852
  python run_experiment.py --resume <folder> --redo c.liv.25C    # repeat one step
  python run_experiment.py --report <folder>           # rebuild the report only

At any prompt: Enter = done, s = skip that step, q = quit (progress is kept; --resume carries on).
Ctrl+C stops the current sweep safely (laser ramped down and switched off).

Before a real run: Kinesis app and Thorlabs power meter app CLOSED (they hold the USB connections),
serial numbers in config/bench.toml, and `python 01_characterisation/check_instruments.py` passes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oil852.campaign import STAGES, Abort, Campaign, plan, preflight  # noqa: E402
from oil852.config import DATA_ROOT, REPO_ROOT, load_config  # noqa: E402

DEFAULT_CAMPAIGN = REPO_ROOT / "config" / "campaign.toml"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--campaign", default=str(DEFAULT_CAMPAIGN), help="campaign file (default config/campaign.toml)")
    p.add_argument("--config", default=None, help="bench file (default config/bench.toml)")
    p.add_argument("--mode", choices=["auto", "manual-driver", "manual", "sim"], default=None,
                   help="override [campaign] mode")
    p.add_argument("--tec", choices=["auto", "manual"], default=None, help="override [campaign] tec_control")
    p.add_argument("--stages", nargs="+", choices=STAGES, default=None, help="override [campaign] stages")
    p.add_argument("--resume", type=Path, default=None, help="campaign folder to carry on")
    p.add_argument("--redo", nargs="+", default=[], help="with --resume: step ids (or prefixes) to run again")
    p.add_argument("--list", action="store_true", help="print the steps and exit")
    p.add_argument("--report", type=Path, default=None, help="rebuild the report for a campaign folder and exit")
    p.add_argument("--on-error", choices=["ask", "skip", "stop"], default=None)
    a = p.parse_args()

    if a.resume or a.report:
        folder = (a.resume or a.report).resolve()
        camp_file = folder / "campaign.toml"
        if not camp_file.exists():
            sys.exit(f"{folder} is not a campaign folder (no campaign.toml)")
        camp = load_config(camp_file)
    else:
        camp = load_config(a.campaign)
        folder = None
    cc = camp.get("campaign", {})
    mode = a.mode or cc.get("mode", "auto")
    if a.resume and a.mode is None:
        mode = json.loads((folder / "state.json").read_text()).get("mode", mode)
    stages = a.stages or cc.get("stages", STAGES)
    bench = load_config(a.config)

    if folder is None and not a.list:
        root = DATA_ROOT / "campaigns"
        folder = root / f"{datetime.now():%Y-%m-%d_%H%M%S}_{cc.get('name', 'campaign')}{'_sim' if mode == 'sim' else ''}"
        folder.mkdir(parents=True)
        shutil.copy2(a.campaign, folder / "campaign.toml")
        shutil.copy2(a.config or (REPO_ROOT / "config" / "bench.toml"), folder / "bench.toml")

    c = Campaign(camp=camp, bench_cfg=bench, folder=folder or Path("."), mode=mode,
                 tec_control=a.tec or cc.get("tec_control", "auto"),
                 on_error=a.on_error or cc.get("on_error", "ask"), bench_config_path=a.config)
    if folder and (folder / "state.json").exists():
        c.state = json.loads((folder / "state.json").read_text())
    c.state["mode"] = mode
    for prefix in a.redo:
        for sid in [s for s in c.state["done"] if s.startswith(prefix)]:
            del c.state["done"][sid]

    steps = plan(c, stages)
    if a.list:
        print(f"Mode {mode}, stages {', '.join(stages)}:")
        for st in steps:
            tag = " (bench only)" if st.needs_bench else ""
            done = c.state["done"].get(st.id, {}).get("status")
            print(f"  {st.id:28s} {st.title}{tag}{f'  [{done}]' if done else ''}")
        return
    if a.report:
        from oil852.report import build_report
        print(f"Report: {build_report(c)}")
        return

    c.save_state()
    c.log(f"Campaign {folder.name}: mode {mode}, TEC {c.tec_control}, stages {', '.join(stages)}")
    if not preflight(c):
        sys.exit("Stopped before starting. Resume later with --resume " + str(folder))
    try:
        c.run(steps)
        c.log(f"\nCampaign finished. Report: {folder / 'report.html'}")
    except (Abort, KeyboardInterrupt):
        c.log(f"\nStopped. Progress saved. Carry on with:\n  python run_experiment.py --resume \"{folder}\"")
        from oil852.report import build_report
        try:
            build_report(c)
            c.log(f"Partial report: {folder / 'report.html'}")
        except Exception as exc:
            c.log(f"(partial report failed: {exc})")
    finally:
        c.cleanup()
        c.save_state()


if __name__ == "__main__":
    main()
