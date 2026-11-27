/*
 * tb/trip.h: classifying a fault or alert on the testbed's rails, and what to switch off (SPEC §3.1, §3.5, §8.4).
 *
 * Plain C, no hardware: the caller takes a snapshot (U_EXP2's inputs, which rails it has enabled, and each
 * INA226's current, bus voltage and Mask/Enable AFF flag) and switches off the rails in the result.
 *
 * What the board can tell (SPEC §3.1, §3.4):
 *  - SLOT_FAULT_N is every TPS2553 FAULT wired together; it asserts after a 5-10 ms deglitch "during
 *    overcurrent, overtemperature, or reverse-voltage conditions" (SLVS841E). The rail that is limiting reads at
 *    or near its trip current, or sags; that is how the fault is attributed. The KVM rail has no monitor.
 *  - PM_ALERT_N is every INA226 ALERT wired together. With LEN = 1 each monitor's AFF stays set until its
 *    Mask/Enable is read, which says which rail crossed its firmware limit (the descriptor's current).
 *  - S5's 5 V is a TPS259474L circuit breaker: latched off while S5_PG is low and EN_5V_S5 high.
 *  - VSYS_PG low while the MCU still runs means the input breaker's output is collapsing.
 *  - PRESENT_N high on a powered slot: the coupon was pulled while powered (SPEC §3.5 forbids it).
 *
 * The actions: the rails in `off` go off (a slot's 5 V with its 3.3 V); `shed_one` asks the budget for its
 * next victim (VSYS over its limit: S5 first, SPEC §8.4); `all_off` turns everything off.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_TRIP_H_
#define TB_TRIP_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/rails.h"

#ifdef __cplusplus
extern "C" {
#endif

struct tb_rail_obs {
	bool monitored; /* this rail has an INA226 */
	bool valid;     /* and it answered */
	int32_t current_ua;
	int32_t bus_mv;
	bool alert;     /* AFF was set in its Mask/Enable */
};

struct tb_trip_snapshot {
	uint32_t on;          /* rails whose EN the firmware drives on */
	uint32_t settling;    /* of those, the ones enabled less than the settling time ago */
	bool fault_low;       /* SLOT_FAULT_N asserted */
	bool alert_low;       /* PM_ALERT_N asserted */
	bool vsys_pg;         /* VSYS_PG high: the input breaker's output is good */
	bool s5_pg;           /* S5_PG high */
	uint8_t absent;       /* bit n-1: PRESENT_N of slot n reads high */
	struct tb_rail_obs rail[TB_RAIL_COUNT];
	struct tb_rail_obs vsys;
	uint32_t vsys_limit_ma;
};

struct tb_trip_cfg {
	uint32_t trip_min_ma[TB_RAIL_COUNT]; /* each switch's minimum trip */
	uint32_t limit_pct;   /* a limiting rail reads at least this % of its minimum trip */
	int32_t uv_3v3_mv;    /* an enabled 3.3 V slot rail below this is sagging */
	int32_t uv_5v_mv;
	int32_t dead_mv;      /* an enabled rail below this never came up (or latched off) */
	int32_t live_mv;      /* a disabled rail above this is being fed from somewhere */
	int32_t live_ua;      /* or draws more than this */
};

enum tb_finding_kind {
	TB_F_VSYS_PG_LOW = 1,
	TB_F_COUPON_REMOVED,   /* slot */
	TB_F_S5_BREAKER,       /* rail = 5V_S5 */
	TB_F_MONITOR_LOST,     /* rail: enabled, its INA226 did not answer */
	TB_F_SWITCH_LIMIT,     /* rail, value = uA */
	TB_F_FAULT_KVM,        /* SLOT_FAULT_N with no measured rail at its limit, the KVM rail on */
	TB_F_FAULT_UNATTRIBUTED,
	TB_F_ALERT,            /* rail, value = uA */
	TB_F_ALERT_UNATTRIBUTED,
	TB_F_VSYS_OVER,        /* value = VSYS uA */
	TB_F_RAIL_DEAD,        /* rail, value = mV */
	TB_F_RAIL_SAG,         /* rail, value = mV (report only) */
	TB_F_RAIL_LIVE_OFF,    /* rail, value = mV (report only: nothing left to switch off) */
};

#define TB_TRIP_MAX_FINDINGS 32

struct tb_finding {
	uint8_t kind;
	int8_t rail; /* -1 when none */
	int8_t slot; /* 0 when none */
	int32_t value;
};

struct tb_trip_result {
	uint8_t n;
	bool truncated;
	struct tb_finding f[TB_TRIP_MAX_FINDINGS];
	uint32_t off;
	bool shed_one;
	bool all_off;
};

/* Defaults for the thresholds (trip_min_ma left 0: the caller fills it from the board map). */
void tb_trip_cfg_defaults(struct tb_trip_cfg *cfg);
void tb_trip_classify(const struct tb_trip_cfg *cfg, const struct tb_trip_snapshot *s, struct tb_trip_result *out);
const char *tb_finding_str(uint8_t kind);

#ifdef __cplusplus
}
#endif

#endif /* TB_TRIP_H_ */
