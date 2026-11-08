# PrettyCool Caliper

A 150 mm digital caliper that remembers its readings and sends them wirelessly.

> **Status: rev A in design.** Nothing has been built or tested. Every figure here is a
> design target until the prototype passes [bring-up](docs/bringup.md).

| | |
|---|---|
| Sensing | AS5311 magnetic linear encoder over 2 mm-pole tape (0.488 µm counts), plus an experimental 8-phase capacitive scale on its own PCB, read side by side |
| Brains | ESP32-S3-MINI-1: BLE 5 and Wi-Fi |
| Display | 1.14 in colour IPS: big reading, live graph, go/no-go gauge, stats |
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
| [docs/simulation.md](docs/simulation.md) | SPICE checks of the power path and the capacitive front-end |
| [docs/firmware.md](docs/firmware.md) | ESP-IDF firmware: sensing, UI, BLE, Wi-Fi, storage, power |
| [docs/app.md](docs/app.md) | Web Bluetooth companion page |
| [docs/assembly.md](docs/assembly.md) | Ordering (JLCPCB), sourcing, assembly |
| [docs/bringup.md](docs/bringup.md) | Bring-up and acceptance tests |
