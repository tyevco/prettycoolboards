/*
 * U_CC, the TUSB320LAI Type-C detect chip on I2C1 (SPEC §3.8, §8.4): read only, plus the INTERRUPT_STATUS
 * clear. Callers hold tb_lock.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_TYPEC_H_
#define TB_TYPEC_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/budget.h"

struct tb_cc_read {
	int err;
	bool id_ok;
	uint8_t id[8];
	uint8_t r08, r09, r0a, rev;
	enum tb_source src;
	bool int_pending;
	bool cleared;
};

/* Read DEVICE_ID, 0x08, 0x09, 0x0A and REVISION; with clear_int, release INT_N if INTERRUPT_STATUS is set. */
int tb_cc_read(struct tb_cc_read *r, bool clear_int);

#endif /* TB_TYPEC_H_ */
