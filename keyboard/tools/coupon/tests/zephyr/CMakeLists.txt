# coupon_desc on Zephyr v4.5.0, native_sim: the descriptor read through the real AT24 EEPROM driver, and the
# TCA9548A slot mux's build-time and naming facts. Built and run by tests/test_zephyr_app.py (marked slow).
# -DCOUPON_IMAGE_INC=<dir> names the directory holding coupon_image.inc (written by the test).
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(coupon_desc_zephyr)

target_sources(app PRIVATE src/main.c)
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../.. ${COUPON_IMAGE_INC})
target_compile_options(app PRIVATE -Wextra -Wshadow -Werror)
