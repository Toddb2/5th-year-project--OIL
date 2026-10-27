# Project history and roadmap

## Aim

Build and characterise a modulator-free, optically injection-locked QKD transmitter, and take it towards deployment: fibre network → airborne (drone) platform → satellite payload context, linked to the group's Hub Optical Ground Station (HOGS) and the Integrated Quantum Networks Hub's SPOQC CubeSat programme.

## Phase 1 (Sep–Oct 2026): monolithic OIL photonic integrated circuit

- The project began with a monolithic master–slave OIL transmitter chip (14-pin butterfly) on loan from the University of Glasgow, which integrates the master, a variable optical attenuator and the slave on one die.
- A PC/104-format (95.9 × 90.2 mm) carrier PCB was designed in KiCad 8: custom chip symbol and butterfly footprint, 50 Ω controlled-impedance RF lines (Hammerstad–Jensen) to the bias tees, stitched ground plane (~400 vias), TVS protection upstream of the bias-tee chokes, zero DRC errors and every net verified with a scripted connectivity checker. *(KiCad files: add to `hardware/pcb/`.)*
- A wired breakout was built and pin-mapped for first light with a KLD101 and TTC001.
- Both loaned packages turned out to have broken pins, so the chips were set aside.

## Phase 2 (Oct 2026 →): discrete 852 nm OIL bench

Rebuilt from discrete parts so every element can be controlled and measured separately: DBR852PN master, FPL852P Fabry–Perot slave, PM circulator, VOA, 99:1 couplers, bias tee and AWG. Another group member is designing laser-mount PCBs for this bench.

## Stages and status

| Stage | Folder | Status |
|---|---|---|
| 1. Single-laser characterisation (L–I–V, T0, tuning, stability) | `01_characterisation/` | Scripts ready and tested in simulation; first DBR measurements next |
| 2. CW injection locking (VOA calibration, OSA spectra, locking map vs injection ratio) | `02_injection_locking/` | Ready; needs the slave on a ≥ 1 A driver and OSA access |
| 3. Pulsed operation (gain switching, master phase steps) | `03_pulsed/` | AWG double-pulse setup proven into 50 Ω; laser pulsing next |
| 4. QKD (COW / DPS / BB84 patterns, QBER, key rate) | `04_qkd/` | Pattern generation and analysis ready; needs SPADs, time tagger and an interferometer |
| 5. Fibre spools, then drone and satellite context | — | Planned |

## Related work

- 4th-year project: [KORUZA FSO-QKD](https://github.com/Toddb2/4th-year-project---KORUZA-FSO-QKD), free-space BB84 link modelling and a low-cost FSO terminal.
- `qkd-noise-study` (separate repository): how FSO channel noise and quantum-hardware noise combine for BB84, B92 and BBM92.
