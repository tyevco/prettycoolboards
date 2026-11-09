# PrettyCool Caliper

A 150 mm digital caliper that remembers its readings and sends them wirelessly.

> **Status (2026-11-08): rev A designed, not built.** Schematics captured (ERC clean, 2 waived); both boards laid
> out and routed (KiCad 10.0.8 DRC + schematic parity: 0 errors, 0 unconnected); both fab packages pass
> `release.py`, including the jlcplace placement gate (slider 0 red, 1 yellow; the J50 land matches its part since
> phase 4); the mechanics pass the clash
> check against the routed board; the firmware builds for the ESP32-S3 and passes its host tests. Nothing has been
> fabricated, flashed, printed or measured, and no SPICE simulation has been run. Every figure here is a design
> target until the prototype passes [bring-up](docs/bringup.md).

| | |
|---|---|
| Sensing | AS5311 magnetic linear encoder over 2 mm-pole tape (0.488 µm internal resolution: the 1.95 µm quadrature count interpolated with the 12-bit SSI position), plus an experimental 8-phase capacitive scale on its own PCB, read side by side |
| Brains | ESP32-S3-MINI-1: BLE 5 and Wi-Fi |
| Display | 1.14 in colour IPS, landscape: big reading, live graph, go/no-go gauge, stats |
| Wireless | BLE HID keyboard (types the reading into any spreadsheet), a companion GATT app, a Wi-Fi web page, MQTT/HTTP push |
| Memory | Thousands of readings with timestamps and tolerance profiles; CSV export over USB, Wi-Fi or BLE |
| Smarts | Tolerance / go-no-go, min/max/mean/σ stats, IMU wake-on-pickup and auto-hold |
| Power | 500 mAh LiPo, USB-C charging (BQ25180), fuel gauge, buck-boost 3V3 |
| Body | Rev A: printed slider on a ground 20 × 4 mm flat-stock beam. Rev B: CNC-machined drawings |

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System overview, decisions and the alternatives that were rejected, power budget |
| [hardware/design/SPEC.md](hardware/design/SPEC.md) | **Architecture of record**: boards, placement, power tree, pin map |
| [docs/electronics.md](docs/electronics.md) | Schematics, boards, ERC/DRC status, renders |
| [docs/mechanical.md](docs/mechanical.md) | Beam, slider housing, gibs, jaws; printed rev A and machined rev B |
| [docs/simulation.md](docs/simulation.md) | Placeholder: the SPICE checks of the power path and the capacitive front-end are not written or run yet |
| [docs/firmware.md](docs/firmware.md) | ESP-IDF firmware: sensing, UI, BLE, Wi-Fi, storage, power |
| [docs/app.md](docs/app.md) | Web Bluetooth companion page |
| [docs/assembly.md](docs/assembly.md) | Ordering (JLCPCB), sourcing, assembly |
| [docs/bringup.md](docs/bringup.md) | Placeholder: the bring-up and acceptance test plan is not written yet |
