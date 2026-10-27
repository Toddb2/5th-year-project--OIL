# Hardware

- **Lasers:** Thorlabs DBR852PN (852 nm DBR, master, 24 mW) and FPL852P (852 nm Fabry–Perot, slave, 300 mW), both 14-pin butterfly, Type 1 pinout ([../docs/wiring.md](../docs/wiring.md)).
- **Mounts:** Arroyo 203 butterfly mount (needs the E1/E2 adapters in the wiring doc); group-designed laser-mount PCBs to follow.
- **Drivers and temperature:** 2 × Thorlabs KLD101 (230 mA max), 2 × TTC001. A ≥ 1 A driver is needed for the FP slave.
- **Optics:** V800PA VOA, 850 nm PM circulator, 2 × PN850R1A2 99:1 PM couplers, FC/APC PM patch cords, narrow-key mating sleeves.
- **RF:** Mini-Circuits ZFBT-6G-FT+ bias tee(s), Active Technologies AWG-5064, 3 dB SMA pads.
- **Measurement:** PM100D + silicon sensor, OSA (lab), Thorlabs CCS spectrometer, DET08CFC photodiode, Tektronix 4 Series MSO.

`pcb/` is for the KiCad 8 carrier board from phase 1 (PC/104 format, 50 Ω RF lines, DRC clean): add the project files, BOM and design notes there.
