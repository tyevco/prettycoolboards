/*
 * tb/ina226.h: INA226 register arithmetic (TI SBOS547; the JLC copy read here is its Chinese edition
 * ZHCS078A, the same register map).
 *
 * Plain C, no I2C: the caller reads and writes the 16-bit registers (big-endian on the wire) and uses these
 * to set them up and to convert what it reads.
 *
 * Register map (SBOS547 Table 4 / ZHCS078A 表 4): 00h Configuration (POR 4127h), 01h Shunt Voltage (2.5 uV/LSB,
 * signed), 02h Bus Voltage (1.25 mV/LSB), 03h Power (25 x Current_LSB), 04h Current (Current_LSB, signed),
 * 05h Calibration, 06h Mask/Enable, 07h Alert Limit, FEh Manufacturer ID (5449h), FFh Die ID (2260h).
 *
 * Calibration, as Zephyr v4.5.0's ti,ina226 driver does it (drivers/sensor/ti/ina2xx/ina226.c,
 * INA226_DT_CAL): CAL = round(0.00512 / (Current_LSB x R_shunt)). The current LSB must be rounded UP so that
 * 32768 x LSB reaches the shunt's full scale (81.92 mV / R), or the current register clips below it
 * (SPEC §3.4; nets.check() enforces the same rule).
 *
 * Alerts (SBOS547 §7.6.7): one function at a time (SOL, SUL, BOL, BUL, POL; the highest set bit wins), plus
 * CNVR. With LEN = 1 the ALERT pin and AFF stay asserted until Mask/Enable is read (or Configuration is
 * written), which is what lets the board service find which of the 13 monitors pulled the shared PM_ALERT_N
 * low. Reading Mask/Enable also clears CVRF.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_INA226_H_
#define TB_INA226_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TB_INA226_REG_CONFIG      0x00
#define TB_INA226_REG_SHUNT       0x01
#define TB_INA226_REG_BUS         0x02
#define TB_INA226_REG_POWER       0x03
#define TB_INA226_REG_CURRENT     0x04
#define TB_INA226_REG_CAL         0x05
#define TB_INA226_REG_MASK_ENABLE 0x06
#define TB_INA226_REG_ALERT_LIMIT 0x07
#define TB_INA226_REG_MFR_ID      0xFE
#define TB_INA226_REG_DIE_ID      0xFF

#define TB_INA226_MFR_ID      0x5449 /* "TI" */
#define TB_INA226_DIE_ID      0x2260
#define TB_INA226_CONFIG_POR  0x4127
#define TB_INA226_CONFIG_RST  0x8000
/* Bit 14 is reserved and reads 1 (POR 4127h); compare a read-back under this mask. */
#define TB_INA226_CONFIG_MASK 0x0FFF
#define TB_INA226_CAL_MAX     0x7FFF

/* Mask/Enable (06h) */
#define TB_INA226_ME_SOL  (1u << 15)
#define TB_INA226_ME_SUL  (1u << 14)
#define TB_INA226_ME_BOL  (1u << 13)
#define TB_INA226_ME_BUL  (1u << 12)
#define TB_INA226_ME_POL  (1u << 11)
#define TB_INA226_ME_CNVR (1u << 10)
#define TB_INA226_ME_AFF  (1u << 4)
#define TB_INA226_ME_CVRF (1u << 3)
#define TB_INA226_ME_OVF  (1u << 2)
#define TB_INA226_ME_APOL (1u << 1)
#define TB_INA226_ME_LEN  (1u << 0)

/* Operating modes (Configuration bits 2:0). */
enum tb_ina226_mode {
	TB_INA226_MODE_POWER_DOWN = 0,
	TB_INA226_MODE_SHUNT_TRIG = 1,
	TB_INA226_MODE_BUS_TRIG = 2,
	TB_INA226_MODE_BOTH_TRIG = 3,
	TB_INA226_MODE_POWER_DOWN2 = 4,
	TB_INA226_MODE_SHUNT_CONT = 5,
	TB_INA226_MODE_BUS_CONT = 6,
	TB_INA226_MODE_BOTH_CONT = 7,
};

/* The shunt's full scale in uA: 81.92 mV / R. */
uint32_t tb_ina226_full_scale_ua(uint32_t shunt_uohm);
/* CAL for a current LSB and shunt, rounded to nearest and clamped to 15 bits (0 if either is 0). */
uint16_t tb_ina226_cal(uint32_t lsb_ua, uint32_t shunt_uohm);
/* Does 32768 x LSB reach the shunt's full scale? (The rule behind INA226_CURRENT_LSB_UA.) */
bool tb_ina226_lsb_covers_full_scale(uint32_t lsb_ua, uint32_t shunt_uohm);
/* The smallest whole-uA LSB that covers the full scale. */
uint32_t tb_ina226_min_lsb_ua(uint32_t shunt_uohm);
/* The current where the current register saturates (32767 x LSB), in uA. */
uint32_t tb_ina226_current_clip_ua(uint32_t lsb_ua);

int32_t tb_ina226_current_ua(int16_t raw, uint32_t lsb_ua);
int32_t tb_ina226_shunt_nv(int16_t raw);
/* The current from the shunt register alone (V / R), independent of CAL: a cross-check of CAL. */
int32_t tb_ina226_shunt_current_ua(int16_t raw, uint32_t shunt_uohm);
uint32_t tb_ina226_bus_uv(uint16_t raw);
uint32_t tb_ina226_power_uw(uint16_t raw, uint32_t lsb_ua);
/* What the current register should read for a shunt register value and CAL: shunt x CAL / 2048. */
int32_t tb_ina226_expected_current_raw(int16_t shunt_raw, uint16_t cal);

/* Configuration from averaging count (1, 4, ..., 1024), conversion times in us (140 ... 8244) and mode.
 * Returns -1 if a value is not one the INA226 offers. */
int32_t tb_ina226_config(uint32_t avg, uint32_t vbus_us, uint32_t vsh_us, enum tb_ina226_mode mode);
void tb_ina226_config_decode(uint16_t cfg, uint32_t *avg, uint32_t *vbus_us, uint32_t *vsh_us,
			     enum tb_ina226_mode *mode);
/* Time for one complete (averaged) result in continuous mode, us (0 in power-down or triggered modes). */
uint32_t tb_ina226_sample_period_us(uint16_t cfg);

/* Alert limit for a Shunt Over-Limit at a current, rounded up and clamped to 0x7FFF. */
uint16_t tb_ina226_sol_limit(uint32_t current_ua, uint32_t shunt_uohm);
/* The current a SOL limit corresponds to, uA. */
uint32_t tb_ina226_sol_current_ua(uint16_t limit, uint32_t shunt_uohm);
/* Alert limit for a Bus Under-Limit at a voltage (1.25 mV/LSB), rounded down. */
uint16_t tb_ina226_bul_limit(uint32_t bus_mv);

/* The voltage at the coupon: the bus reading less I x R_series (SPEC §3.1: shunt, switch, jumper). */
int32_t tb_ina226_coupon_mv(int32_t bus_mv, int32_t current_ua, uint32_t r_series_mohm);

#ifdef __cplusplus
}
#endif

#endif /* TB_INA226_H_ */
