/*
 * tb/selftest.h: the arithmetic of the lane sanity scan and the test-coupon self-test (SPEC §10 step 7).
 *
 * Plain C, no hardware. The test coupon (keyboard/hardware/design/sheets/test_coupon.py) carries:
 *  - a ladder of five 1.00 kOhm 0.1 % resistors from its +3V3: AN0..AN3 = 0.2, 0.4, 0.6, 0.8 x V(+3V3 at the
 *    coupon), ratiometric with VREF+ (= VDDA, from the same slot LDO; SPEC §3.1);
 *  - four switched loads: G0 30 ohm on +3V3 (110 mA), G1 5 ohm on +3V3 (the current-limit test), G2 30 ohm on
 *    +5V (167 mA), G3 3.33 ohm on +5V (the S1-S4 current-limit test; never on S5);
 *  - an SN74LV165A loopback on SPI2: CS1_N low loads G0..G5, INJ, SYNC; with CS0_N low, 16 clocks in mode 0
 *    return bits 15..8 = G0, G1, G2, G3, G4, G5, INJ, SYNC and bits 7..0 = the first byte sent on MOSI;
 *  - IRQ_N pulled low while G5 (or INJ) is high, a status LED on G4.
 *
 * The slot's series resistance (shunt, switch, jumper; SPEC §3.1) from two lane readings at two currents: with
 * r = tap / VREF+, k the ladder ratio, Rs the series resistance and I the coupon's current,
 *   r = k (1 - I Rs / VREF)   =>   Rs = VREF (r0 - r1) / (r0 I1 - r1 I0),
 * exact in k, so the ladder's own tolerance cancels.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_SELFTEST_H_
#define TB_SELFTEST_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TB_PPM 1000000u

/* code / 2^bits, in ppm of the reference. */
uint32_t tb_lane_ratio_ppm(uint32_t code, unsigned bits);
/* Q16 ratio (a descriptor's expected lane ratio) in ppm. */
uint32_t tb_q16_to_ppm(uint16_t q16);
/* |measured - expected| <= tol; err = measured - expected. */
bool tb_lane_check(uint32_t code, unsigned bits, uint32_t expect_ppm, uint32_t tol_ppm, int32_t *err_ppm);
/* Two converters on one lane agree to within tol (each scaled to ppm of its own reference). */
bool tb_lanes_agree(uint32_t code_a, unsigned bits_a, uint32_t code_b, unsigned bits_b, uint32_t tol_ppm,
		    int32_t *diff_ppm);

enum tb_lane_state {
	TB_LANE_LOW = 0,   /* below 1 % of full scale */
	TB_LANE_MID,
	TB_LANE_HIGH,      /* above 99 % of full scale */
};
enum tb_lane_state tb_lane_state(uint32_t code, unsigned bits);

/* Series resistance in mOhm from ratios r0, r1 (ppm) at coupon currents i0, i1 (uA) and VREF+ (mV).
 * Returns 0, or -1 if the currents or ratios give no answer (equal currents, i1 <= i0, r1 >= r0). */
int tb_series_mohm(uint32_t r0_ppm, uint32_t r1_ppm, int32_t i0_ua, int32_t i1_ua, uint32_t vref_mv,
		   int32_t *out_mohm);

struct tb_loopback {
	uint8_t g;     /* bit k = G<k> */
	bool inj;
	bool sync;
	uint8_t echo;  /* the first byte sent on MOSI */
};
void tb_loopback_decode(uint16_t rx, struct tb_loopback *out);
uint16_t tb_loopback_expect(uint8_t g, bool inj, bool sync, uint8_t tx);

/* A load step: the current rose by about V / R. expect_ua is V / R; tol in % of it. */
bool tb_load_step_ok(int32_t i_off_ua, int32_t i_on_ua, int32_t v_mv, uint32_t r_mohm, uint32_t tol_pct,
		     int32_t *expect_ua);
/* A current-limit reading inside the switch's trip window [min (1 - tol), max (1 + tol)]. */
bool tb_climit_ok(int32_t i_ua, const uint32_t trip_ma[3], uint32_t tol_pct);

#ifdef __cplusplus
}
#endif

#endif /* TB_SELFTEST_H_ */
