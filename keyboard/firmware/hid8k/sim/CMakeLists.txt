# hid8k-sim: hid8k's USB device code on native_sim, against Zephyr's own USB host stack on the
# virtual bus (drivers/usb/udc/udc_virtual.c, drivers/usb/uhc/uhc_virtual.c). See README.md.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)

get_filename_component(HID8K_DIR ${CMAKE_CURRENT_LIST_DIR}/.. ABSOLUTE)

# The board's prj.conf first, so the simulation runs the firmware's own configuration (queue
# depth, HID buffer count, event queue sizes, logging), then the simulation's additions.
if(NOT DEFINED CONF_FILE)
  set(CONF_FILE "${HID8K_DIR}/prj.conf;${CMAKE_CURRENT_LIST_DIR}/prj.conf")
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(hid8k_sim)

# The firmware, unchanged: the same four files the board build compiles.
target_sources(app PRIVATE
  ${HID8K_DIR}/src/main.c
  ${HID8K_DIR}/src/hid8k.c
  ${HID8K_DIR}/src/cdc_console.c
  ${HID8K_DIR}/src/usb_device.c
)

# The host side: two small class drivers for Zephyr's host stack and the test.
target_sources(app PRIVATE
  src/host_hid.c
  src/host_cdc.c
  src/sim_main.c
)

target_include_directories(app PRIVATE
  ${HID8K_DIR}/src
  ${ZEPHYR_BASE}/subsys/usb/host
  ${ZEPHYR_BASE}/drivers/usb/uhc
)

# The same warnings as the board build (see ../CMakeLists.txt).
target_compile_options(app PRIVATE -Wextra -Wshadow -Wno-type-limits)

if(CONFIG_HID8K_SIM_UHC_HS_FIX)
  # A copy of Zephyr v4.5.0's virtual host controller with its microframe timer kept after a bus
  # reset (drivers/uhc_virtual_hs.c says what changed and why).
  target_sources(app PRIVATE drivers/uhc_virtual_hs.c)
  target_include_directories(app PRIVATE ${ZEPHYR_BASE}/drivers/usb)
  # Zephyr's code, built with Zephyr's warnings, not this app's stricter -Wextra.
  set_source_files_properties(drivers/uhc_virtual_hs.c PROPERTIES COMPILE_OPTIONS
    "-Wno-extra;-Wno-unused-parameter")
endif()
