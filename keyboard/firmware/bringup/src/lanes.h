/*
 * Lane reads (SPEC §4.4, §6.2): every lane on its primary converter and on every other converter that
 * reaches its pin, and VDDA from VREFINT. Callers hold tb_lock (it serialises the shell and the self-test).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_LANES_H_
#define TB_LANES_H_

#include <stdint.h>

int tb_lanes_init(void);
/* Primary converter of slot/lane: code and resolution. */
int tb_lane_read(int slot, int lane, int32_t *code, unsigned *bits, uint8_t *adc, uint8_t *ch);
/* A converter by number (1, 2, 4) and channel, with the board's lane acquisition time. */
int tb_adc_read(uint8_t adc, uint8_t ch, int32_t *code, unsigned *bits);
/* VDDA in mV (from VREFINT and its factory calibration), and the die temperature in milli-degrees C. */
int tb_vdda_mv(int32_t *mv);
int tb_die_temp_mc(int32_t *mc);

#endif /* TB_LANES_H_ */
