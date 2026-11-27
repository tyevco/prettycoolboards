/*
 * Rail names (SPEC §3.1).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include "tb/rails.h"

static const char *const names[TB_RAIL_COUNT] = {
	"+3V3_S1", "+3V3_S2", "+3V3_S3", "+3V3_S4", "+3V3_S5",
	"+5V_S1", "+5V_S2", "+5V_S3", "+5V_S4", "+5V_S5", "+5V_KVM",
};

const char *tb_rail_name(int rail)
{
	return tb_rail_valid(rail) ? names[rail] : "?";
}

int tb_rail_from_name(const char *name)
{
	if (name == NULL) {
		return -1;
	}
	for (int i = 0; i < TB_RAIL_COUNT; i++) {
		if (strcmp(name, names[i]) == 0) {
			return i;
		}
	}
	return -1;
}
