/*
 * The coupon descriptor EEPROM (M24C02 at 0x50 on the slot's own mux channel; SPEC §4.6): read, parse, and
 * write (16-byte pages, 5 ms write cycle, ACK polling: ST DocID024020 §5.1.2). Callers hold tb_lock and power
 * the slot's +3V3 first.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_DESCIO_H_
#define TB_DESCIO_H_

#include <stddef.h>
#include <stdint.h>

#include "tb/desc.h"

/* Read the descriptor's bytes (header first, then as many as it declares). *len: bytes read. */
int tb_descio_read(int slot, uint8_t *buf, size_t cap, size_t *len);
/* Read and parse into tb.desc[slot - 1] and tb.desc_err[slot - 1]; returns the tb_desc_err, or a negative
 * errno below TB_DESC_ERR_SPACE for a bus error. */
int tb_descio_load(int slot, uint8_t *raw, size_t cap, size_t *len);
int tb_descio_write(int slot, const uint8_t *buf, size_t len);

#define TB_DESCIO_BUS_ERR (-100)

#endif /* TB_DESCIO_H_ */
