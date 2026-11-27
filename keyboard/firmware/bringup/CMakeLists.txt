# bringup: the rev A testbed motherboard's bring-up firmware (SPEC §10), for the board kbd_testbed_a.
#   west build -b kbd_testbed_a keyboard/firmware/bringup            (the board root is set below)
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)

# The out-of-tree board kbd_testbed_a lives in keyboard/firmware/boards/: no -DBOARD_ROOT needed (one still works).
list(APPEND BOARD_ROOT ${CMAKE_CURRENT_LIST_DIR}/..)

# The simulated board (sim/): native_sim with the generated overlay of kbd_testbed_a's nodes on emulated
# controllers, and the board's bindings (prettycool,*) on the devicetree search path.
if(BOARD MATCHES "^native_sim")
  set(TB_BOARD_DIR ${CMAKE_CURRENT_LIST_DIR}/../boards/prettycool/kbd_testbed_a)
  list(APPEND DTS_ROOT ${TB_BOARD_DIR})
  list(APPEND DTC_OVERLAY_FILE ${TB_BOARD_DIR}/sim/kbd_testbed_a_sim.overlay)
  list(APPEND EXTRA_CONF_FILE ${CMAKE_CURRENT_LIST_DIR}/sim/sim.conf)
else()
  list(APPEND EXTRA_CONF_FILE ${CMAKE_CURRENT_LIST_DIR}/usb.conf)
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(tb_bringup)

include(${CMAKE_CURRENT_SOURCE_DIR}/../lib/tb_lib.cmake)

target_sources(app PRIVATE
  ${TB_LIB_SOURCES}
  src/main.c
  src/board.c
  src/monitors.c
  src/typec.c
  src/service.c
  src/events.c
  src/out.c
  src/lanes.c
  src/descio.c
  src/slot.c
  src/coupon_test.c
  src/cmds.c
)
if(CONFIG_BRINGUP_USB)
  target_sources(app PRIVATE src/usb.c src/cdc_shell.c)
endif()
if(CONFIG_BRINGUP_SIM)
  target_sources(app PRIVATE
    sim/world.c
    sim/sim_cmds.c
    sim/emul_tca9535.c
    sim/emul_ina226.c
    sim/emul_tca9548a.c
    sim/emul_tusb320.c
    sim/emul_eeprom.c
    sim/emul_sim165.c
  )
  target_include_directories(app PRIVATE sim)
endif()
target_include_directories(app PRIVATE ${TB_LIB_INCLUDE} ${TB_BOARD_MAP_INCLUDE} src)

# Stricter than Zephyr's defaults, for this app's own sources (and the lib) only. -Wno-type-limits: with
# -Wextra, Zephyr v4.5.0's usbd_msg.h warns in every file that includes usbd.h (as in hid8k).
target_compile_options(app PRIVATE -Wextra -Wshadow -Wno-type-limits)
