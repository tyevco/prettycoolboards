/*
 * tb/rails.h: the switched rails of the rev A testbed motherboard and their numbering (SPEC §3.1).
 *
 * Plain C, no hardware dependency. The numbering is shared with the generated board map (TB_RAIL_ID_* in
 * tb_board_map.h, from keyboard/firmware/boards/gen_board.py); the lib's tests check that the two agree.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_RAILS_H_
#define TB_RAILS_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TB_SLOTS 5

enum tb_rail_id {
	TB_RAIL_3V3_S1 = 0,
	TB_RAIL_3V3_S2,
	TB_RAIL_3V3_S3,
	TB_RAIL_3V3_S4,
	TB_RAIL_3V3_S5,
	TB_RAIL_5V_S1,
	TB_RAIL_5V_S2,
	TB_RAIL_5V_S3,
	TB_RAIL_5V_S4,
	TB_RAIL_5V_S5,
	TB_RAIL_5V_KVM,
	TB_RAIL_COUNT,
};

#define TB_RAIL_BIT(r) (1u << (unsigned)(r))
#define TB_RAIL_MASK_ALL ((1u << TB_RAIL_COUNT) - 1u)
/* Rails behind a TPS2553 (all but S5's 5 V, which is a TPS259474L breaker with its own power-good). */
#define TB_RAIL_MASK_TPS2553 (TB_RAIL_MASK_ALL & ~TB_RAIL_BIT(TB_RAIL_5V_S5))

static inline bool tb_rail_valid(int rail)
{
	return rail >= 0 && rail < TB_RAIL_COUNT;
}

static inline int tb_rail_3v3(int slot)
{
	return (slot >= 1 && slot <= TB_SLOTS) ? slot - 1 : -1;
}

static inline int tb_rail_5v(int slot)
{
	return (slot >= 1 && slot <= TB_SLOTS) ? TB_SLOTS + slot - 1 : -1;
}

static inline bool tb_rail_is_3v3(int rail)
{
	return rail >= TB_RAIL_3V3_S1 && rail <= TB_RAIL_3V3_S5;
}

/* Slot 1-5 of a slot rail, 0 for the KVM rail, -1 for an invalid id. */
static inline int tb_rail_slot(int rail)
{
	if (tb_rail_is_3v3(rail)) {
		return rail + 1;
	}
	if (rail >= TB_RAIL_5V_S1 && rail <= TB_RAIL_5V_S5) {
		return rail - TB_SLOTS + 1;
	}
	return rail == TB_RAIL_5V_KVM ? 0 : -1;
}

/* Both rails of a slot. */
static inline uint32_t tb_slot_rail_mask(int slot)
{
	if (slot < 1 || slot > TB_SLOTS) {
		return 0;
	}
	return TB_RAIL_BIT(tb_rail_3v3(slot)) | TB_RAIL_BIT(tb_rail_5v(slot));
}

/* "+3V3_S1" ... "+5V_S5", "+5V_KVM"; "?" for an invalid id. */
const char *tb_rail_name(int rail);

/* The rail id for a name as tb_rail_name() spells it, or -1. */
int tb_rail_from_name(const char *name);

#ifdef __cplusplus
}
#endif

#endif /* TB_RAILS_H_ */
