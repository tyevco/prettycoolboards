# hid8k: 8 kHz HID proof for the NUCLEO-U5A5ZJ-Q
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(hid8k)

target_sources(app PRIVATE
  src/main.c
  src/hid8k.c
  src/cdc_console.c
  src/usb_device.c
)

# Stricter than Zephyr's defaults, for this app's own sources only. -Wno-type-limits: with
# -Wextra, Zephyr v4.5.0's own usbd_msg.h (usbd_msg_type_string(), "type >= 0" on an enum)
# would warn in every file that includes usbd.h.
target_compile_options(app PRIVATE -Wextra -Wshadow -Wno-type-limits)
