/*
 * U_CC reads (see typec.h). Every write goes through tb_tusb320_write_allowed() (SPEC §8.4's never-write list).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/drivers/i2c.h>

#include "board.h"
#include "tb/tusb320.h"
#include "typec.h"

int tb_cc_read(struct tb_cc_read *r, bool clear_int)
{
	const struct i2c_dt_spec *cc = &tb_sig.typec;
	int err;

	memset(r, 0, sizeof(*r));
	r->src = TB_SRC_UNREADABLE;
	err = i2c_burst_read_dt(cc, TB_TUSB320_REG_ID, r->id, sizeof(r->id));
	err = err ? err : i2c_reg_read_byte_dt(cc, TB_TUSB320_REG_CSR08, &r->r08);
	err = err ? err : i2c_reg_read_byte_dt(cc, TB_TUSB320_REG_CSR09, &r->r09);
	err = err ? err : i2c_reg_read_byte_dt(cc, TB_TUSB320_REG_CSR0A, &r->r0a);
	err = err ? err : i2c_reg_read_byte_dt(cc, TB_TUSB320_REG_REVISION, &r->rev);
	r->err = err;
	if (err != 0) {
		return err;
	}
	r->id_ok = tb_tusb320_id_ok(r->id);
	if (!r->id_ok) {
		return -ENODEV; /* another part, or a bus error that reads back plausibly */
	}
	r->src = tb_tusb320_source(r->r08, r->r09);
	r->int_pending = tb_tusb320_int_pending(r->r09);
	if (clear_int && r->int_pending) {
		uint8_t v = tb_tusb320_int_clear_value(r->r09);

		if (tb_tusb320_write_allowed(TB_TUSB320_REG_CSR09, v, r->r09)) {
			err = i2c_reg_write_byte_dt(cc, TB_TUSB320_REG_CSR09, v);
			r->cleared = err == 0;
		}
	}
	return err;
}
