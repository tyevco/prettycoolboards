/*
 * INA226 register arithmetic. See tb/ina226.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stddef.h>

#include "tb/ina226.h"

#define FULL_SCALE_UV 81920u   /* 32768 x 2.5 uV */
#define SHUNT_LSB_NV  2500
#define BUS_LSB_UV    1250u

static const uint16_t avg_tab[8] = {1, 4, 16, 64, 128, 256, 512, 1024};
static const uint16_t ct_tab[8] = {140, 204, 332, 588, 1100, 2116, 4156, 8244};

uint32_t tb_ina226_full_scale_ua(uint32_t shunt_uohm)
{
	if (shunt_uohm == 0) {
		return 0;
	}
	/* 81920 uV / (R_uohm / 1e6 ohm) = 81920e6 / R_uohm uA */
	return (uint32_t)(((uint64_t)FULL_SCALE_UV * 1000000u) / shunt_uohm);
}

uint16_t tb_ina226_cal(uint32_t lsb_ua, uint32_t shunt_uohm)
{
	uint64_t den = (uint64_t)lsb_ua * shunt_uohm;
	uint64_t cal;

	if (den == 0) {
		return 0;
	}
	/* 0.00512 / (LSB[A] x R[ohm]) = 5.12e9 / (LSB[uA] x R[uohm]); DIV_ROUND_CLOSEST as Zephyr's driver. */
	cal = (5120000000ull + den / 2u) / den;
	return cal > TB_INA226_CAL_MAX ? TB_INA226_CAL_MAX : (uint16_t)cal;
}

bool tb_ina226_lsb_covers_full_scale(uint32_t lsb_ua, uint32_t shunt_uohm)
{
	/* 32768 x LSB >= 81920e6 / R  <=>  32768 x LSB x R >= 81920e6 (exact integer compare) */
	return (uint64_t)32768u * lsb_ua * shunt_uohm >= (uint64_t)FULL_SCALE_UV * 1000000u;
}

uint32_t tb_ina226_min_lsb_ua(uint32_t shunt_uohm)
{
	uint64_t num = (uint64_t)FULL_SCALE_UV * 1000000u;
	uint64_t den = (uint64_t)32768u * shunt_uohm;

	if (den == 0) {
		return 0;
	}
	return (uint32_t)((num + den - 1u) / den);
}

uint32_t tb_ina226_current_clip_ua(uint32_t lsb_ua)
{
	return 32767u * lsb_ua;
}

int32_t tb_ina226_current_ua(int16_t raw, uint32_t lsb_ua)
{
	return (int32_t)raw * (int32_t)lsb_ua;
}

int32_t tb_ina226_shunt_nv(int16_t raw)
{
	return (int32_t)raw * SHUNT_LSB_NV;
}

int32_t tb_ina226_shunt_current_ua(int16_t raw, uint32_t shunt_uohm)
{
	int64_t nv = (int64_t)raw * SHUNT_LSB_NV;

	if (shunt_uohm == 0) {
		return 0;
	}
	/* nV / uohm = mA; x 1000 for uA. Round half away from zero. */
	nv *= 1000;
	if (nv >= 0) {
		return (int32_t)((nv + shunt_uohm / 2) / shunt_uohm);
	}
	return (int32_t)((nv - (int64_t)(shunt_uohm / 2)) / (int64_t)shunt_uohm);
}

uint32_t tb_ina226_bus_uv(uint16_t raw)
{
	return (uint32_t)(raw & 0x7FFFu) * BUS_LSB_UV;
}

uint32_t tb_ina226_power_uw(uint16_t raw, uint32_t lsb_ua)
{
	return (uint32_t)raw * 25u * lsb_ua;
}

int32_t tb_ina226_expected_current_raw(int16_t shunt_raw, uint16_t cal)
{
	/* SBOS547 Eq. 3: Current = Shunt x CAL / 2048 (the device truncates; so does this). */
	int64_t v = (int64_t)shunt_raw * cal;

	return (int32_t)(v / 2048);
}

static int idx_of(const uint16_t *tab, uint32_t v)
{
	for (int i = 0; i < 8; i++) {
		if (tab[i] == v) {
			return i;
		}
	}
	return -1;
}

int32_t tb_ina226_config(uint32_t avg, uint32_t vbus_us, uint32_t vsh_us, enum tb_ina226_mode mode)
{
	int a = idx_of(avg_tab, avg);
	int b = idx_of(ct_tab, vbus_us);
	int s = idx_of(ct_tab, vsh_us);

	if (a < 0 || b < 0 || s < 0 || (unsigned)mode > 7u) {
		return -1;
	}
	return (int32_t)(((unsigned)a << 9) | ((unsigned)b << 6) | ((unsigned)s << 3) | (unsigned)mode);
}

void tb_ina226_config_decode(uint16_t cfg, uint32_t *avg, uint32_t *vbus_us, uint32_t *vsh_us,
			     enum tb_ina226_mode *mode)
{
	if (avg != NULL) {
		*avg = avg_tab[(cfg >> 9) & 7u];
	}
	if (vbus_us != NULL) {
		*vbus_us = ct_tab[(cfg >> 6) & 7u];
	}
	if (vsh_us != NULL) {
		*vsh_us = ct_tab[(cfg >> 3) & 7u];
	}
	if (mode != NULL) {
		*mode = (enum tb_ina226_mode)(cfg & 7u);
	}
}

uint32_t tb_ina226_sample_period_us(uint16_t cfg)
{
	uint32_t avg, vb, vs;
	enum tb_ina226_mode mode;

	tb_ina226_config_decode(cfg, &avg, &vb, &vs, &mode);
	switch (mode) {
	case TB_INA226_MODE_SHUNT_CONT:
		return vs * avg;
	case TB_INA226_MODE_BUS_CONT:
		return vb * avg;
	case TB_INA226_MODE_BOTH_CONT:
		return (vb + vs) * avg;
	default:
		return 0;
	}
}

uint16_t tb_ina226_sol_limit(uint32_t current_ua, uint32_t shunt_uohm)
{
	/* uA x uohm = pV; / 1000 = nV; / 2500 nV per LSB, rounded up. */
	uint64_t pv = (uint64_t)current_ua * shunt_uohm;
	uint64_t lsb = (pv + (uint64_t)SHUNT_LSB_NV * 1000u - 1u) / ((uint64_t)SHUNT_LSB_NV * 1000u);

	return lsb > 0x7FFFu ? 0x7FFFu : (uint16_t)lsb;
}

uint32_t tb_ina226_sol_current_ua(uint16_t limit, uint32_t shunt_uohm)
{
	if (shunt_uohm == 0) {
		return 0;
	}
	return (uint32_t)(((uint64_t)limit * SHUNT_LSB_NV * 1000u) / shunt_uohm);
}

uint16_t tb_ina226_bul_limit(uint32_t bus_mv)
{
	uint32_t lsb = (bus_mv * 1000u) / BUS_LSB_UV;

	return lsb > 0x7FFFu ? 0x7FFFu : (uint16_t)lsb;
}

int32_t tb_ina226_coupon_mv(int32_t bus_mv, int32_t current_ua, uint32_t r_series_mohm)
{
	/* uA x mohm = nV; / 1e6 = mV (rounded to nearest). */
	int64_t drop_nv = (int64_t)current_ua * (int64_t)r_series_mohm;
	int64_t drop_mv = (drop_nv >= 0 ? drop_nv + 500000 : drop_nv - 500000) / 1000000;

	return bus_mv - (int32_t)drop_mv;
}
