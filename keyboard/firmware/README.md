# PrettyCool Keyboard firmware

Custom firmware on Zephyr ([concept §6](../docs/concept.md#_6-firmware-custom-on-zephyr)), pinned to Zephyr v4.5.0
(commit 41d10b5) for rev A ([SPEC §8.1](../hardware/design/SPEC.md#_8-1-versions-and-board)). One Zephyr
application per folder, as the caliper's ESP-IDF firmware lives in `caliper/firmware/`.

> **Status (2026-11-27):** one bring-up application, written and compiled, never run on hardware. Nothing here has
> been measured. The testbed firmware itself (board `kbd_testbed_a`, the scan engine, the coupon drivers) does not
> exist yet.

| Folder | What | Board | Status |
|---|---|---|---|
| [hid8k/](hid8k/README.md) | The 8 kHz HID proof: an NKRO keyboard and a vendor stats report at bInterval 1 (125 µs), paced from the completion callback, a CDC ACM console, and the host tool that measures report rate and jitter. Condition 2 of [SPEC §1](../hardware/design/SPEC.md#_1-purpose-and-what-rev-a-must-prove) | `nucleo_u5a5zj_q` | compiled with Ubuntu's arm-none-eabi GCC 13.2, not run |

Build any of them from the repository root into `keyboard/firmware/build/` (git-ignored, and left out of the docs
site):

```sh
west build -p always -b nucleo_u5a5zj_q keyboard/firmware/hid8k -d keyboard/firmware/build/hid8k
```

Next, after the 8 kHz proof: the scan engine on the Nucleo with breakout "coupons"
([SPEC §10](../hardware/design/SPEC.md#_10-bring-up-order), step 3).
