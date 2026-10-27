# Physics notes

A short reference for the ideas each stage tests. Equations are implemented in `oil852/`.

## Why optical injection locking (OIL) for QKD

A gain-switched laser diode makes short pulses, but each pulse starts from spontaneous emission, so its optical phase is random. Injecting light from a continuous master laser seeds every slave pulse, so:

- the slave pulses inherit the master's **phase**, coherence and narrow linewidth, and its wavelength;
- a small current step on the master *between* slave pulses shifts the master's phase (through the carrier-induced refractive index change), and the next slave pulse carries that shift. This encodes phase **without an external modulator** (the scheme of Toshiba Europe, and of the Glasgow monolithic chip this project started with).

That gives the pulse trains for COW, DPS and phase-encoded BB84 from two lasers, a circulator and an AWG.

## Locking range

With detuning Δω = ω_master − ω_slave, injection ratio ρ = P_inj / P_slave, linewidth enhancement factor α and coupling coefficient κ, a locked solution exists for

    −κ √ρ √(1 + α²)  ≤  Δω  ≤  κ √ρ

(Mogensen et al., IEEE JQE 21, 784 (1985)). The range grows as √ρ and is lopsided towards negative detuning by √(1 + α²). The dynamically stable part is narrower. κ ≈ (1/τ_in)(1 − R)/√R with τ_in the round-trip time; for a ~1 mm FP chip κ ≈ 5 × 10¹⁰ s⁻¹, giving a few GHz at −20 dB injection.

**Unit conversions at 852 nm:** 1 pm ≈ 0.413 GHz. The DBR852PN tunes about 2 pm/mA ≈ 0.83 GHz/mA, so a locking range of a few GHz is a **few mA** of master current. Temperature gives coarse tuning (0.06 nm/°C ≈ 25 GHz/°C), current the fine tuning. FP mode spacing (~0.1 nm ≈ 40 GHz) sets how often a lock repeats as the master is tuned.

## Gain switching

The slave is biased just below threshold and driven with short current pulses. The carrier density overshoots, and the laser emits one short relaxation-oscillation spike (tens of ps for a fast diode; limited here by the drive edges and the 5 GHz photodiode). Bias, pulse amplitude and pulse width trade pulse width against timing jitter and trailing ringing.

## Protocols

| Protocol | Slave | Master | Bob |
|---|---|---|---|
| **COW** | Pulse pairs: bit 0 = pulse/empty, 1 = empty/pulse, decoy = pulse/pulse | CW | Data line: time of arrival. Monitor line: delay-line interferometer checks coherence between neighbouring pulses (visibility) |
| **DPS** | Pulse every slot | Step between pulses: 0 or π phase | One-slot delay-line interferometer; which port clicks gives the bit |
| **BB84 (phase)** | Pulse every slot | Steps giving 0, π/2, π, 3π/2 (two bases) | Interferometer with basis choice |

Phase error from imperfect interference: e = (1 − V)/2, where V is the fringe visibility.

## Secure key rate benchmark

Asymptotic decoy-state BB84 (Lo, Ma and Chen, PRL 94, 230504 (2005)):

    R = q { −Q_μ f H₂(E_μ) + Q₁ [1 − H₂(e₁)] }

with Q_μ = Y₀ + 1 − e^(−ημ), E_μ = [½Y₀ + e_d(1 − e^(−ημ))]/Q_μ, Q₁ = (Y₀ + η) μ e^(−μ), e₁ = (½Y₀ + e_d η)/(Y₀ + η). COW and DPS have their own proofs; this repo models their detection rates and QBER and uses decoy BB84 as the benchmark.

## 852 nm in fibre

Standard telecom fibre (SMF-28, cut-off ~1260 nm) is **few-mode** at 852 nm: modal noise and lost interferometer visibility. Use fibre that is single-mode at 852 nm (780HP class, ~3.5 dB/km). At 3.5 dB/km the decoy-BB84 key reaches zero around 14 km with the default detector numbers, which is why 852 nm suits free-space links (silicon SPADs, low atmospheric absorption) more than long fibre.
