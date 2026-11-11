# PrettyCool Caliper firmware

ESP-IDF 5.4 firmware for the caliper's ESP32-S3-MINI-1-N4R2: AS5311 magnetic sensing (PCNT + SSI), the
experimental capacitive scale, an LVGL UI on the ST7789, NimBLE (custom GATT service + Battery + Device
Information + HID keyboard), Wi-Fi with a web page and MQTT/HTTP push, TinyUSB CDC + MSC, a LittleFS reading
log, and the BQ25180 / MAX17048 / LSM6DSO / IIS2MDC power side. The LSM6DSO (gyroscope + accelerometer) wakes
the caliper on pickup and, while it is awake, feeds an orientation filter (roll, pitch, a relative yaw, "steady")
that turns the display 180° when the caliper is held top edge down. The IIS2MDC compass, polled at 10 Hz and used
only after `bu compass cal`, gives that filter a magnetic heading that limits the yaw's drift: the local field
next to the steel beam, not north.

> **Status:** **builds with `idf.py build` on ESP-IDF v5.4.2** (esp32s3, 4 MB layout, 0 warnings; image
> 1 711 168 B, 3.3 % of the app slot free with the bring-up commands; `CONFIG_CALIPER_BRINGUP=n` gave 23.5 KB
> back before the LSM6DSO change and was not rebuilt after it) but has **never run on hardware**. The LSM6DSO
> driver and the orientation filter are written from the datasheet and tested on synthetic motion only. The
> IIS2MDC compass driver takes its register values from ST's driver sources (the datasheet's register map was not
> read) and its part of the filter is tested on synthetic fields only. The portable core passes its host tests
> (72 groups, 2741 checks, ASan + UBSan, `-Werror`), and the log store its own (4 groups, 2614 checks).
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
| `components/measure` | portable core: units, rounding, tolerance, stats, log records, GATT codecs, settings JSON, CSV, buttons, HID map, `orient.c` (orientation from gyroscope + accelerometer samples, with the compass as a yaw reference) |
| `components/sensor_mag`, `sensor_cap` | AS5311 and the experimental capacitive scale |
| `components/caliper_core` | event bus, live state, commands |
| `components/bringup` | the `bu` bring-up checks on the USB console ([docs/bringup.md](../docs/bringup.md)), among them `bu compass` and the calibration `bu compass cal`; `bringup_eval.c` (the pass/fail rules) is portable |
| `components/power` | BQ25180, MAX17048, the LSM6DSO driver and its 50 Hz sampler (`imu.c`; the chip → board axis mapping is at its top), the IIS2MDC compass driver (`compass.c`, with its own axis table; compiled and host-tested, never run), backlight / piezo / LED, deep sleep |
| `components/store`, `ui`, `ble`, `caliper_wifi`, `caliper_usb` | the rest |
| `test/host` | host unit tests (`caliper_tests`: the portable core and the bring-up rules; `store_tests`: `store.c` against `test/host/stubs`) |
