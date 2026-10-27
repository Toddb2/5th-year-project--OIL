# Wiring

Check every link with a meter before powering anything (see [bench_settings.md](bench_settings.md)).

## Laser package: 14-pin butterfly, Type 1 (both DBR852PN and FPL852P)

| Pin | Function | Pin | Function |
|---|---|---|---|
| 1 | TEC + | 14 | TEC − |
| 2 | Thermistor | 13 | Case |
| 3 | Monitor PD anode | 12 | n/c |
| 4 | Monitor PD cathode | 11 | Laser cathode (−) |
| 5 | Thermistor | 10 | Laser anode (+) |
| 6–9 | n/c | | |

## Drivers to the mount

| Link | From | To | Notes |
|---|---|---|---|
| E1 laser | KLD101 LD output (DB9) | Mount LASER | Cathode-grounded drive: KLD101 pin 8 → anode, pin 3 → cathode. **Pins 1 and 5 linked** in the KLD101-side plug (interlock). Straight DB9 cable only if the mount uses the Thorlabs pinout |
| E2 TEC | TTC001 TEC output (DB15) | Mount TEC | CAB420-15 or straight DB15. TTC001 side: thermistor on 3/4, TEC + on 5–7, TEC − on 13–15 |

### Arroyo 203 butterfly mount adapters

The Arroyo mount has Thorlabs-shaped connectors with **different** pins. Never plug a Thorlabs controller straight in.

| Adapter | KLD101 / CAB420-15 side | Arroyo side |
|---|---|---|
| E1 (laser) | DB9 male into KLD101: pin 8 | → Arroyo 8 and 9 (anode) |
| | pin 3 | → Arroyo 4 and 5 (cathode) |
| | pins 1–5 strapped inside this plug only | not carried through (Arroyo 5 is the cathode) |
| E2 (TEC) | DB9 male into CAB420-15's 9-pin end: pin 4 | → Arroyo 1 and 2 (TEC +) |
| | pin 5 | → Arroyo 3 and 4 (TEC −) |
| | pins 2 and 3 | → Arroyo 7 and 8 (thermistor) |

Arroyo screw-terminal colour code: 1 TEC+ orange, 2 thermistor blue, 3 PD anode green, 4 PD cathode white, 5 thermistor violet, 10 anode red, 11 cathode black, 13 case brown, 14 TEC− yellow. The lab's mount has been modified before (a coax and an SMA board inside, a hand label that disagrees with the colour code): meter every terminal.

## RF (stages 3 and 4)

| Link | From | To | Notes |
|---|---|---|---|
| E7 | AWG CH1 (SMA), 3 dB pad at the AWG | Bias tee A **RF** | Slave gain-switching pulses. 50 Ω cable ≤ 1 m |
| E8 | Bias tee A **RF&DC** | Laser pins 10 (centre) / 11 (braid) via the mount's LD-input coax | Keep the coax < 10 cm; no series resistor |
| E9 | Driver DC (mount "Driver DC output") | Bias tee A **DC** / GND | Centre (anode side) → DC, shield → GND |
| E10–E12 | AWG CH2 → bias tee B → master | Only for master phase steps (stage 4) | Ross: only the slave needs RF for locking and gain switching |
| E5 | AWG CH3 (DC mode, High-Z) | VOA control BNC | 0–5 V only |

Bias tee DC limit: 500 mA. Keep the slave's DC limit at or below 450 mA while it is in circuit.

## Fibre path (stage 2 onwards)

Master → VOA (master path only: rated 100 mW; the slave exceeds that near 450 mA) → 99:1 coupler B (1 % tap = injection monitor) → PM circulator port 1 → port 2 ↔ slave → port 3 → 99:1 coupler A (1 % tap → power meter / OSA / fast photodiode via attenuators). All PM fibre, FC/APC (green) to FC/APC, narrow-key mating sleeves to hold the polarisation axis.
