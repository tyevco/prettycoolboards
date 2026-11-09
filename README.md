# prettycoolboards

**Docs site:** <https://tyevco.github.io/prettycoolboards/>

Open hardware boards designed as code. The schematics and PCBs are generated
from Python into KiCad 10, routed with Freerouting plus a grid router, and
gated by ERC, DRC and schematic parity before any fab output is written.
Enclosures and mechanics are in build123d.

## Boards

| Board | Status | |
|---|---|---|
| [PrettyCool Caliper](caliper/README.md) | rev A in design | 150 mm digital caliper: magnetic and capacitive sensing, ESP32-S3 with BLE + Wi-Fi, colour IPS, reading memory, go/no-go, USB-C |

## Repository layout

```
tools/        shared Python → KiCad generator toolchain (see tools/README.md)
caliper/      one folder per board: hardware/, firmware/, app/, docs/
.vitepress/   docs site (VitePress), published to GitHub Pages by .github/workflows/docs.yml
```

The hardware toolchain runs on Linux: KiCad 10 (`kicad-cli` + `pcbnew`), Java 21 +
Freerouting 2.1, ngspice and build123d. On Windows, run it in WSL.

```sh
npm ci && npm run docs:dev   # preview the docs site locally
```
