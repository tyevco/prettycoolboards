# PrettyCool Caliper firmware

ESP-IDF 5.4 firmware for the caliper's ESP32-S3-MINI-1-N4R2: AS5311 magnetic sensing (PCNT + SSI), the
experimental capacitive scale, an LVGL UI on the ST7789, NimBLE (custom GATT service + Battery + Device
Information + HID keyboard), Wi-Fi with a web page and MQTT/HTTP push, TinyUSB CDC + MSC, a LittleFS reading
log, and the BQ25180 / MAX17048 / LIS2DW12 power side.

> **Status:** **builds with `idf.py build` on ESP-IDF v5.4.2** (esp32s3, 4 MB layout, 0 warnings; image
> 1 689 152 B, 4.5 % of the app slot free with the bring-up commands, 6 % with `CONFIG_CALIPER_BRINGUP=n`) but
> has **never run on hardware**. The portable core passes its host tests (59 groups, 1276 checks, ASan + UBSan,
> `-Werror`), and the log store its own (3 groups, 2589 checks).
> Details, design, the 2026-11-07 review fixes and the list of unverified items:
> [docs/firmware.md](../docs/firmware.md).

## Build

```sh
. ~/esp/esp-idf/export.sh             # ESP-IDF v5.4.x with the esp32s3 tools installed
idf.py set-target esp32s3
idf.py build                          # 4 MB flash (N4R2), the default
# 8 MB (N8R2):
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.8mb" set-target esp32s3 build
idf.py -p /dev/ttyACM0 flash monitor  # see docs/firmware.md §10 once TinyUSB owns the USB port
```

The pin map comes from `caliper/hardware/design/nets.py`. After changing it, regenerate the header (the build
stops if it is stale):

```sh
python3 tools/gen_pins.py
```

## Host tests

```sh
cmake -S test/host -B build-host -G Ninja && cmake --build build-host && ctest --test-dir build-host --output-on-failure
```

## Layout

| Path | |
|---|---|
| `main/app_main.c` | tasks and wiring |
| `main/proto/caliper_gatt.h` | the BLE contract shared with `caliper/app` |
| `main/board_pins.h` | generated from nets.py by `tools/gen_pins.py` |
| `components/measure` | portable core: units, rounding, tolerance, stats, log records, GATT codecs, settings JSON, CSV, buttons, HID map |
| `components/sensor_mag`, `sensor_cap` | AS5311 and the experimental capacitive scale |
| `components/caliper_core` | event bus, live state, commands |
| `components/bringup` | the `bu` bring-up checks on the USB console ([docs/bringup.md](../docs/bringup.md)); `bringup_eval.c` (the pass/fail rules) is portable |
| `components/store`, `ui`, `ble`, `caliper_wifi`, `caliper_usb`, `power` | the rest |
| `test/host` | host unit tests (`caliper_tests`: the portable core and the bring-up rules; `store_tests`: `store.c` against `test/host/stubs`) |
