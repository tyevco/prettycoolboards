/*
 * Host shim for compiling Zephyr v4.5.0's subsys/crc/crc32_sw.c outside Zephyr (tests/test_c_header.py):
 * only the declarations that file needs. The CRC code itself is Zephyr's, unmodified.
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef SHIM_ZEPHYR_SYS_CRC_H_
#define SHIM_ZEPHYR_SYS_CRC_H_
#include <stddef.h>
#include <stdint.h>
#define __weak __attribute__((weak))
uint32_t crc32_ieee(const uint8_t *data, size_t len);
uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len);
uint32_t crc32_mpeg2(const uint8_t *data, size_t len);
uint32_t crc32_mpeg2_update(uint32_t crc, const uint8_t *data, size_t len);
#endif
