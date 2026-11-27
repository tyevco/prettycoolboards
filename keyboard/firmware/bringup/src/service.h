/*
 * The board service thread (see service.c).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_SERVICE_H_
#define TB_SERVICE_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/budget.h"
#include "tb/trip.h"

/* From the USB message callback: queued, never blocks. */
void tb_service_usb(enum tb_usb_event ev, uint32_t value);
/* Poll now (EXP_INT_N, or a command that changed something). */
void tb_service_kick(void);
void tb_service_start(void);
uint32_t tb_service_period_ms(void);
void tb_service_set_period(uint32_t ms);

/* With tb_lock held: a fresh snapshot for the classifier (all_rails also reads the monitors of off rails),
 * the board's classifier thresholds, and applying a result. */
int tb_snapshot(struct tb_trip_snapshot *s, uint16_t *inputs, bool all_rails);
void tb_trip_cfg_board(struct tb_trip_cfg *cfg);
void tb_apply_trip(const struct tb_trip_result *res);

#endif /* TB_SERVICE_H_ */
