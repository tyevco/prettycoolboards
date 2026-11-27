/*
 * Lane and test-coupon arithmetic. See tb/selftest.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stddef.h>

#include "tb/selftest.h"

uint32_t tb_lane_ratio_ppm(uint32_t code, unsigned bits)
{
	uint64_t full;

	if (bits == 0 || bits > 24) {
		return 0;
	}
	full = 1ull << bits;
	return (uint32_t)(((uint64_t)code * TB_PPM + full / 2u) / full);
}

uint32_t tb_q16_to_ppm(uint16_t q16)
{
	return (uint32_t)(((uint64_t)q16 * TB_PPM + 32768u) >> 16);
}

bool tb_lane_check(uint32_t code, unsigned bits, uint32_t expect_ppm, uint32_t tol_ppm, int32_t *err_ppm)
{
	int32_t err = (int32_t)tb_lane_ratio_ppm(code, bits) - (int32_t)expect_ppm;

	if (err_ppm != NULL) {
		*err_ppm = err;
	}
	return (err < 0 ? -err : err) <= (int32_t)tol_ppm;
}

bool tb_lanes_agree(uint32_t code_a, unsigned bits_a, uint32_t code_b, unsigned bits_b, uint32_t tol_ppm,
		    int32_t *diff_ppm)
{
	int32_t d = (int32_t)tb_lane_ratio_ppm(code_a, bits_a) - (int32_t)tb_lane_ratio_ppm(code_b, bits_b);

	if (diff_ppm != NULL) {
		*diff_ppm = d;
	}
	return (d < 0 ? -d : d) <= (int32_t)tol_ppm;
}

enum tb_lane_state tb_lane_state(uint32_t code, unsigned bits)
{
	uint32_t r = tb_lane_ratio_ppm(code, bits);

	if (r < TB_PPM / 100u) {
		return TB_LANE_LOW;
	}
	if (r > TB_PPM - TB_PPM / 100u) {
		return TB_LANE_HIGH;
	}
	return TB_LANE_MID;
}

int tb_series_mohm(uint32_t r0_ppm, uint32_t r1_ppm, int32_t i0_ua, int32_t i1_ua, uint32_t vref_mv,
		   int32_t *out_mohm)
{
	/* Rs[mOhm] = vref_mV x (r0 - r1) x 1e6 / (r0 i1 - r1 i0), r in ppm, i in uA. */
	int64_t den = (int64_t)r0_ppm * i1_ua - (int64_t)r1_ppm * i0_ua;
	int64_t num = (int64_t)vref_mv * ((int64_t)r0_ppm - (int64_t)r1_ppm) * 1000000;

	if (i1_ua <= i0_ua || r1_ppm >= r0_ppm || den <= 0) {
		return -1;
	}
	*out_mohm = (int32_t)((num + den / 2) / den);
	return 0;
}

void tb_loopback_decode(uint16_t rx, struct tb_loopback *out)
{
	uint8_t hi = (uint8_t)(rx >> 8);

	out->g = 0;
	/* bit 15 = H = G0 (first out) ... bit 10 = C = G5, bit 9 = B = INJ, bit 8 = A = SYNC */
	for (int k = 0; k < 6; k++) {
		if (hi & (0x80u >> k)) {
			out->g |= (uint8_t)(1u << k);
		}
	}
	out->inj = (hi & 0x02u) != 0;
	out->sync = (hi & 0x01u) != 0;
	out->echo = (uint8_t)rx;
}

uint16_t tb_loopback_expect(uint8_t g, bool inj, bool sync, uint8_t tx)
{
	uint8_t hi = 0;

	for (int k = 0; k < 6; k++) {
		if (g & (1u << k)) {
			hi |= (uint8_t)(0x80u >> k);
		}
	}
	hi |= inj ? 0x02u : 0u;
	hi |= sync ? 0x01u : 0u;
	return (uint16_t)(((uint16_t)hi << 8) | tx);
}

bool tb_load_step_ok(int32_t i_off_ua, int32_t i_on_ua, int32_t v_mv, uint32_t r_mohm, uint32_t tol_pct,
		     int32_t *expect_ua)
{
	int64_t exp_ua, d, tol;

	if (r_mohm == 0) {
		return false;
	}
	/* V / R: mV / mOhm = A; x 1e6 for uA. */
	exp_ua = ((int64_t)v_mv * 1000000 + r_mohm / 2) / r_mohm;
	if (expect_ua != NULL) {
		*expect_ua = (int32_t)exp_ua;
	}
	d = (int64_t)i_on_ua - i_off_ua - exp_ua;
	tol = exp_ua * tol_pct / 100;
	return (d < 0 ? -d : d) <= tol;
}

bool tb_climit_ok(int32_t i_ua, const uint32_t trip_ma[3], uint32_t tol_pct)
{
	int64_t lo = (int64_t)trip_ma[0] * (100 - tol_pct) * 10;
	int64_t hi = (int64_t)trip_ma[2] * (100 + tol_pct) * 10;

	return i_ua >= lo && i_ua <= hi;
}
