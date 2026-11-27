# keyboard/firmware/lib: the testbed's pure logic, for any Zephyr application (or a host build).
#   include(${CMAKE_CURRENT_LIST_DIR}/../lib/tb_lib.cmake)
#   target_sources(app PRIVATE ${TB_LIB_SOURCES})
#   target_include_directories(app PRIVATE ${TB_LIB_INCLUDE})
# SPDX-License-Identifier: Apache-2.0

set(TB_LIB_DIR ${CMAKE_CURRENT_LIST_DIR})
set(TB_LIB_INCLUDE ${TB_LIB_DIR}/include)
set(TB_LIB_SOURCES
  ${TB_LIB_DIR}/src/rails.c
  ${TB_LIB_DIR}/src/budget.c
  ${TB_LIB_DIR}/src/ina226.c
  ${TB_LIB_DIR}/src/tusb320.c
  ${TB_LIB_DIR}/src/desc.c
  ${TB_LIB_DIR}/src/desc_test_coupon.c
  ${TB_LIB_DIR}/src/trip.c
  ${TB_LIB_DIR}/src/selftest.c
)
# The generated board map (tb_board_map.h), which the tests use for the real numbers.
set(TB_BOARD_MAP_INCLUDE ${TB_LIB_DIR}/../boards/prettycool/kbd_testbed_a/include)
