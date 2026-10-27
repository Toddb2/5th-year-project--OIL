"""Expected performance of the OIL transmitter over fibre: detection rate, QBER and the
asymptotic decoy-state BB84 secure key rate (the standard benchmark), against distance.

  python 04_qkd/keyrate.py
  python 04_qkd/keyrate.py --rep-MHz 20 --visibility 0.95 --spools 1 2 5 10

Fibre and detector numbers come from config/bench.toml ([fibre], [detector]).
At 852 nm the fibre must be single-mode at 852 nm (780HP-class, ~3.5 dB/km). Telecom SMF-28 is
few-mode there, which adds modal noise and interferometer visibility loss.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import json  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from oil852.config import DATA_ROOT, load_config  # noqa: E402
from oil852.qkd import (channel_transmittance, dark_count_prob, detection_prob,  # noqa: E402
                        optimal_mu, qber_from_visibility, qber_with_darks)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rep-MHz", type=float, default=20.0, help="pulse rate (20 MHz = 50 ns slots)")
    p.add_argument("--gate-ns", type=float, default=1.0, help="detection window per slot")
    p.add_argument("--visibility", type=float, default=0.95, help="interferometer visibility -> optical error rate")
    p.add_argument("--bob-loss-dB", type=float, default=3.0, help="Bob's optics (splitter, interferometer, coupling)")
    p.add_argument("--max-km", type=float, default=40.0)
    p.add_argument("--spools", type=float, nargs="*", default=[], help="spool lengths in km to report")
    p.add_argument("--config", default=None)
    a = p.parse_args()
    cfg = load_config(a.config)
    fib, det = cfg["fibre"], cfg["detector"]
    e_d = float(qber_from_visibility(a.visibility))
    Y0 = dark_count_prob(det["dark_count_Hz"], a.gate_ns)
    L = np.linspace(0, a.max_km, 400)
    eta = channel_transmittance(L, fib["attenuation_dB_per_km"], 2 * fib["connector_loss_dB"], a.bob_loss_dB) * det["efficiency"]
    rate_opt = np.array([optimal_mu(e, Y0, e_d)[1] for e in eta]) * a.rep_MHz * 1e6
    mu_fixed = 0.1
    det_rate = detection_prob(mu_fixed, eta, Y0) * a.rep_MHz * 1e6
    qber = qber_with_darks(e_d, 1 - np.exp(-eta * mu_fixed), Y0)

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    ax.semilogy(L, np.clip(rate_opt, 1e-3, None), label="decoy BB84 secure key (optimal mu)")
    ax.semilogy(L, det_rate, "--", label=f"detections, mu = {mu_fixed}")
    ax.set_xlabel("Fibre length (km)")
    ax.set_ylabel("Rate (bit/s)")
    ax.set_ylim(1, None)
    ax.legend(fontsize=8)
    ax.set_title(f"{a.rep_MHz:g} MHz, {fib['attenuation_dB_per_km']} dB/km, det. eff. {det['efficiency']}")
    ax2.plot(L, qber * 100)
    ax2.axhline(11, color="#d1495b", ls=":", lw=1, label="11 % BB84 limit")
    ax2.set_xlabel("Fibre length (km)")
    ax2.set_ylabel("QBER (%)")
    ax2.set_title(f"Visibility {a.visibility} -> optical error {e_d * 100:.1f} %, dark counts {det['dark_count_Hz']:g} Hz")
    ax2.legend(fontsize=8)
    for axx in (ax, ax2):
        axx.grid(alpha=0.3, which="both")
    fig.tight_layout()
    out = DATA_ROOT / "theory"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "keyrate_vs_distance.png", dpi=150)
    report = {}
    for km in [0.0] + list(a.spools):
        e = float(channel_transmittance(km, fib["attenuation_dB_per_km"], 2 * fib["connector_loss_dB"], a.bob_loss_dB) * det["efficiency"])
        mu, r = optimal_mu(e, Y0, e_d)
        report[f"{km:g} km"] = {"eta_total": e, "optimal_mu": mu, "secure_key_bps": r * a.rep_MHz * 1e6,
                                "qber_pct_at_mu0.1": float(qber_with_darks(e_d, 1 - np.exp(-e * mu_fixed), Y0) * 100)}
        print(f"{km:5g} km: total transmittance {e:.3e}, optimal mu {mu:.2f}, "
              f"key {r * a.rep_MHz * 1e6:,.0f} bit/s, QBER {report[f'{km:g} km']['qber_pct_at_mu0.1']:.2f} %")
    zero = L[np.argmax(rate_opt <= 0)] if np.any(rate_opt <= 0) else None
    print(f"Key rate reaches zero at ~{zero:.1f} km" if zero else f"Positive key out to {a.max_km:g} km")
    (out / "keyrate_report.json").write_text(json.dumps(report, indent=2))
    print(f"Saved {out / 'keyrate_vs_distance.png'}")


if __name__ == "__main__":
    main()
