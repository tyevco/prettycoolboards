/*
 * tb/tusb320.h: decoding the TUSB320LAI Type-C detect chip U_CC (TI SLLSEQ8D, Tables 7-12; SPEC §3.8, §8.4).
 *
 * Plain C, no I2C. The firmware only reads U_CC and clears INTERRUPT_STATUS:
 *  - 0x00-0x07 DEVICE_ID: "Addresses 0x07 - 0x00 = {0x00 0x54 0x55 0x53 0x42 0x33 0x32 0x30}" (Table 7), so a
 *    read of eight bytes from 0x00 gives '0' '2' '3' 'B' 'S' 'U' 'T' 0x00 ("TUSB320", last character first).
 *  - 0x08 bits 5:4 CURRENT_MODE_DETECT: 00 Default, 01 Medium, 10 "Audio Charged through accessory - 500 mA",
 *    11 High (Table 8).
 *  - 0x09 bits 7:6 ATTACHED_STATE: 00 not attached, 01 Attached.SRC (DFP), 10 Attached.SNK (UFP), 11 an
 *    accessory; bit 4 INTERRUPT_STATUS, "A write of 1'b1 is required to clear this field" (Table 9).
 *  - 0xA0 REVISION, 0x02 by default (Table 12).
 * Never written (SPEC §8.4): 0x0A DISABLE_TERM, MODE_SELECT, I2C_SOFT_RESET, and 0x45 DISABLE_RD_RP. Any of them
 * can take Rd off CC, and the source would then remove VBUS, the board's only supply.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_TUSB320_H_
#define TB_TUSB320_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/budget.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TB_TUSB320_REG_ID       0x00
#define TB_TUSB320_ID_LEN       8
#define TB_TUSB320_REG_CSR08    0x08
#define TB_TUSB320_REG_CSR09    0x09
#define TB_TUSB320_REG_CSR0A    0x0A
#define TB_TUSB320_REG_CSR45    0x45
#define TB_TUSB320_REG_REVISION 0xA0

#define TB_TUSB320_INT_STATUS   (1u << 4) /* 0x09 bit 4 */

enum tb_tusb320_attach {
	TB_TUSB320_NOT_ATTACHED = 0,
	TB_TUSB320_ATTACHED_SRC = 1,
	TB_TUSB320_ATTACHED_SNK = 2,
	TB_TUSB320_ACCESSORY = 3,
};

/* The eight DEVICE_ID bytes as read from 0x00 upwards. */
bool tb_tusb320_id_ok(const uint8_t id[TB_TUSB320_ID_LEN]);
enum tb_tusb320_attach tb_tusb320_attached(uint8_t csr09);
uint8_t tb_tusb320_current_mode(uint8_t csr08);
/* The budget's source for what 0x08 and 0x09 say (nets.TUSB320_CURRENT_MODE and TYPEC_BUDGET):
 * Attached.SNK: Default, 1.5 A, the charge-through audio accessory (Default), 3.0 A; an accessory state: the
 * accessory level; not attached: not attached; Attached.SRC (impossible with PORT tied low): unreadable. */
enum tb_source tb_tusb320_source(uint8_t csr08, uint8_t csr09);
bool tb_tusb320_int_pending(uint8_t csr09);
/* The byte to write to 0x09 to release INT_N: the byte just read with bit 4 set (SPEC §8.4), so that
 * DRP_DUTY_CYCLE and DISABLE_UFP_ACCESSORY keep their values. */
uint8_t tb_tusb320_int_clear_value(uint8_t csr09);
/* A guard for every write the firmware makes: only 0x09 with tb_tusb320_int_clear_value() of its last read. */
bool tb_tusb320_write_allowed(uint8_t reg, uint8_t value, uint8_t last_csr09);
const char *tb_tusb320_attach_str(enum tb_tusb320_attach a);

#ifdef __cplusplus
}
#endif

#endif /* TB_TUSB320_H_ */
