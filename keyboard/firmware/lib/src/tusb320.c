/*
 * TUSB320LAI decoding (SLLSEQ8D). See tb/tusb320.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include "tb/tusb320.h"

static const uint8_t expect_id[TB_TUSB320_ID_LEN] = {0x30, 0x32, 0x33, 0x42, 0x53, 0x55, 0x54, 0x00};

bool tb_tusb320_id_ok(const uint8_t id[TB_TUSB320_ID_LEN])
{
	for (int i = 0; i < TB_TUSB320_ID_LEN; i++) {
		if (id[i] != expect_id[i]) {
			return false;
		}
	}
	return true;
}

enum tb_tusb320_attach tb_tusb320_attached(uint8_t csr09)
{
	return (enum tb_tusb320_attach)((csr09 >> 6) & 3u);
}

uint8_t tb_tusb320_current_mode(uint8_t csr08)
{
	return (uint8_t)((csr08 >> 4) & 3u);
}

enum tb_source tb_tusb320_source(uint8_t csr08, uint8_t csr09)
{
	switch (tb_tusb320_attached(csr09)) {
	case TB_TUSB320_NOT_ATTACHED:
		return TB_SRC_NOT_ATTACHED;
	case TB_TUSB320_ACCESSORY:
		return TB_SRC_ACCESSORY;
	case TB_TUSB320_ATTACHED_SNK:
		switch (tb_tusb320_current_mode(csr08)) {
		case 0:
			return TB_SRC_DEFAULT;
		case 1:
			return TB_SRC_1A5;
		case 3:
			return TB_SRC_3A0;
		default:
			/* 10: "Audio Charged through accessory - 500 mA": the Default level */
			return TB_SRC_DEFAULT;
		}
	default:
		/* Attached.SRC: the chip acting as a source, impossible with PORT tied low. Trust nothing. */
		return TB_SRC_UNREADABLE;
	}
}

bool tb_tusb320_int_pending(uint8_t csr09)
{
	return (csr09 & TB_TUSB320_INT_STATUS) != 0;
}

uint8_t tb_tusb320_int_clear_value(uint8_t csr09)
{
	return (uint8_t)(csr09 | TB_TUSB320_INT_STATUS);
}

bool tb_tusb320_write_allowed(uint8_t reg, uint8_t value, uint8_t last_csr09)
{
	return reg == TB_TUSB320_REG_CSR09 && value == tb_tusb320_int_clear_value(last_csr09);
}

const char *tb_tusb320_attach_str(enum tb_tusb320_attach a)
{
	switch (a) {
	case TB_TUSB320_NOT_ATTACHED: return "not_attached";
	case TB_TUSB320_ATTACHED_SRC: return "attached_src";
	case TB_TUSB320_ATTACHED_SNK: return "attached_snk";
	case TB_TUSB320_ACCESSORY: return "accessory";
	default: return "?";
	}
}
