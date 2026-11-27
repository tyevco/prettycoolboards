/*
 * The test-coupon self-test (see coupon_test.c).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_COUPON_TEST_H_
#define TB_COUPON_TEST_H_

#include <stdbool.h>
#include <zephyr/shell/shell.h>

struct tb_st_opts {
	bool loads;  /* the G0 and G2 load steps, and the series resistance */
	bool climit; /* the G1 and G3 current-limit steps */
	bool force;  /* run on a coupon whose descriptor is not a test coupon's */
};

/* Prints "@tb step ..." per step and a final "@tb selftest ..."; takes tb_lock per step. */
int tb_selftest_run(const struct shell *sh, int slot, const struct tb_st_opts *o);

#endif /* TB_COUPON_TEST_H_ */
