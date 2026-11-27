# ztest suite for keyboard/firmware/lib, on native_sim/native/64 (or any board).
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(tb_lib_tests)

include(${CMAKE_CURRENT_SOURCE_DIR}/../tb_lib.cmake)

# The C parser is tested against the Python reference encoder's output.
set(TB_VECTORS ${CMAKE_CURRENT_BINARY_DIR}/gen/tb_desc_vectors.h)
add_custom_command(
  OUTPUT ${TB_VECTORS}
  COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/gen
  COMMAND ${CMAKE_COMMAND} -E env PYTHONDONTWRITEBYTECODE=1
          ${PYTHON_EXECUTABLE} -I ${TB_LIB_DIR}/tools/coupon_desc.py --c-vectors ${TB_VECTORS}
  DEPENDS ${TB_LIB_DIR}/tools/coupon_desc.py
  COMMENT "Coupon descriptor test vectors"
)
add_custom_target(tb_desc_vectors DEPENDS ${TB_VECTORS})
add_dependencies(app tb_desc_vectors)

target_sources(app PRIVATE
  ${TB_LIB_SOURCES}
  src/test_rails.c
  src/test_ina226.c
  src/test_budget.c
  src/test_tusb320.c
  src/test_desc.c
  src/test_trip.c
  src/test_selftest.c
)
target_include_directories(app PRIVATE ${TB_LIB_INCLUDE} ${TB_BOARD_MAP_INCLUDE} ${CMAKE_CURRENT_BINARY_DIR}/gen)
target_compile_options(app PRIVATE -Wextra -Wshadow)
