# Safety summary

The full risk assessment is the signed lab document; this is the working checklist.

**Lasers:** 852 nm is invisible near-infrared. The FPL852P reaches ~300 mW (Class 3B); the DBR852PN ~24 mW (Class 3B).
- Goggles rated **OD ≥ 3 at 852 nm** whenever a laser is on; IR viewer card for finding stray light.
- Fibre ends are capped or connected before switching on; never look along a fibre.
- Light paths at bench height only; no free-space beams without enclosure.

**Electrical and laser protection:**
- ESD strap when handling the butterfly packages or the mount.
- Current limits set on the driver **before** the output is enabled: DBR ≤ 230 mA (KLD101 maximum); FP only on a ≥ 1 A driver, limit 500 mA in the first session, never above 1 A or 320 mW.
- TEC on and stable before any laser current; switch-off in reverse.
- Never hot-plug a laser cable with the driver enabled.
- Polarity: cathode grounded, matching the wiring in [wiring.md](wiring.md).

**Bench-specific:**
- VOA control 0–5 V only: AWG DC (High-Z) or a 5 V-limited supply, **never** the MDT693B piezo controller (75 V).
- Slave light never goes through the VOA (rated 100 mW).
- AWG levels checked on the scope into 50 Ω before the bias tee is connected; `config/bench.toml [awg]` caps the levels the scripts will set.
- Bias tee ≤ 500 mA DC; slave DC limit ≤ 450 mA while it is in circuit.
- 20–30 dB attenuation in front of the OSA and the fast photodiode.

**Software protection in this repo:** per-laser current limits in `config/bench.toml`, refusal to run the FP on the KLD101, polarity check, ramped current changes, abort on sensor overload or a current mismatch, and automatic ramp-down and disable on finish, error or Ctrl+C.
