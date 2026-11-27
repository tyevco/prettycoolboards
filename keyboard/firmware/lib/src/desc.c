/*
 * Coupon descriptor, format 1.0 (a proposal pending compiler v0). See tb/desc.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include "tb/desc.h"

uint16_t tb_crc16_ccitt(const uint8_t *data, size_t len)
{
	uint16_t crc = 0xFFFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= (uint16_t)((uint16_t)data[i] << 8);
		for (int b = 0; b < 8; b++) {
			crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
		}
	}
	return crc;
}

static uint16_t rd16(const uint8_t *p)
{
	return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void wr16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
}

static void wr32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

void tb_desc_init(struct tb_desc *d)
{
	memset(d, 0, sizeof(*d));
	d->major = TB_DESC_MAJOR;
	d->minor = TB_DESC_MINOR;
	d->rev = 'A';
	d->slot_mask = TB_DESC_ALL_SLOTS;
}

static bool blank(const uint8_t *buf, size_t n)
{
	for (size_t i = 0; i < n; i++) {
		if (buf[i] != 0xFF) {
			return false;
		}
	}
	return true;
}

int tb_desc_peek_length(const uint8_t *buf, size_t n)
{
	uint16_t len;

	if (n < 8) {
		return TB_DESC_ERR_SHORT;
	}
	if (blank(buf, 8)) {
		return TB_DESC_ERR_BLANK;
	}
	if (buf[0] != TB_DESC_MAGIC0 || buf[1] != TB_DESC_MAGIC1 || buf[2] != TB_DESC_MAGIC2 ||
	    buf[3] != TB_DESC_MAGIC3) {
		return TB_DESC_ERR_MAGIC;
	}
	if (buf[4] != TB_DESC_MAJOR) {
		return TB_DESC_ERR_VERSION;
	}
	len = rd16(&buf[6]);
	if (len < TB_DESC_MIN_LEN || len > TB_DESC_MAX_LEN) {
		return TB_DESC_ERR_LENGTH;
	}
	return len;
}

static int parse_record(struct tb_desc *d, uint8_t type, uint8_t len, const uint8_t *v)
{
	switch (type) {
	case TB_DESC_REC_PAD:
		return TB_DESC_OK;
	case TB_DESC_REC_NAME:
		if (len < 1 || len > TB_DESC_NAME_MAX) {
			return TB_DESC_ERR_RECORD;
		}
		if (d->name[0] != '\0') {
			return TB_DESC_ERR_DUP;
		}
		for (int i = 0; i < len; i++) {
			if (v[i] < 0x20 || v[i] > 0x7E) {
				return TB_DESC_ERR_VALUE;
			}
			d->name[i] = (char)v[i];
		}
		d->name[len] = '\0';
		return TB_DESC_OK;
	case TB_DESC_REC_LANE: {
		struct tb_desc_lane *l;

		if (len != 10) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] > 3) {
			return TB_DESC_ERR_VALUE;
		}
		l = &d->lane[v[0]];
		if (l->present) {
			return TB_DESC_ERR_DUP;
		}
		l->present = true;
		l->flags = v[1];
		l->r_src_ohm = rd16(&v[2]);
		l->cload_pf = rd16(&v[4]);
		l->expect_q16 = rd16(&v[6]);
		l->tol_q16 = rd16(&v[8]);
		return TB_DESC_OK;
	}
	case TB_DESC_REC_GLINE:
		if (len != 3) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] > 5) {
			return TB_DESC_ERR_VALUE;
		}
		if (d->gline_role[v[0]] != TB_G_UNUSED) {
			return TB_DESC_ERR_DUP;
		}
		d->gline_role[v[0]] = v[1];
		d->gline_arg[v[0]] = v[2];
		return TB_DESC_OK;
	case TB_DESC_REC_I2C:
		if (len != 2) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] < 0x08 || v[0] > 0x77) {
			return TB_DESC_ERR_VALUE;
		}
		if (d->n_i2c >= TB_DESC_MAX_I2C) {
			return TB_DESC_ERR_FULL;
		}
		d->i2c[d->n_i2c].addr = v[0];
		d->i2c[d->n_i2c].kind = v[1];
		d->n_i2c++;
		return TB_DESC_OK;
	case TB_DESC_REC_SPI:
		if (len != 6) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] > 1 || v[1] > 3) {
			return TB_DESC_ERR_VALUE;
		}
		if (d->n_spi >= TB_DESC_MAX_SPI) {
			return TB_DESC_ERR_FULL;
		}
		d->spi[d->n_spi].cs = v[0];
		d->spi[d->n_spi].mode = v[1];
		d->spi[d->n_spi].max_hz = rd32(&v[2]);
		d->n_spi++;
		return TB_DESC_OK;
	case TB_DESC_REC_SLOTS:
		if (len != 1) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] == 0 || (v[0] & ~TB_DESC_ALL_SLOTS) != 0) {
			return TB_DESC_ERR_VALUE;
		}
		d->slot_mask = v[0];
		return TB_DESC_OK;
	case TB_DESC_REC_LOAD: {
		struct tb_desc_load *ld;

		if (len != 7) {
			return TB_DESC_ERR_RECORD;
		}
		if (v[0] >= TB_DESC_MAX_LOADS || v[1] > 5 || v[2] > 1 || v[3] > 1 || rd16(&v[4]) == 0 ||
		    (v[6] & ~TB_DESC_ALL_SLOTS) != 0) {
			return TB_DESC_ERR_VALUE;
		}
		ld = &d->load[v[0]];
		if (ld->present) {
			return TB_DESC_ERR_DUP;
		}
		ld->present = true;
		ld->gline = v[1];
		ld->rail = v[2];
		ld->kind = v[3];
		ld->r_mohm = rd16(&v[4]);
		ld->slot_mask = v[6] ? v[6] : TB_DESC_ALL_SLOTS;
		return TB_DESC_OK;
	}
	case TB_DESC_REC_CAL:
		if (len != 6) {
			return TB_DESC_ERR_RECORD;
		}
		if (d->n_cal >= TB_DESC_MAX_CAL) {
			return TB_DESC_ERR_FULL;
		}
		d->cal[d->n_cal].key = rd16(&v[0]);
		d->cal[d->n_cal].value = (int32_t)rd32(&v[2]);
		d->n_cal++;
		return TB_DESC_OK;
	default:
		d->n_unknown++;
		return TB_DESC_OK;
	}
}

int tb_desc_parse(const uint8_t *buf, size_t n, struct tb_desc *out)
{
	struct tb_desc d;
	int len = tb_desc_peek_length(buf, n);
	size_t pos;

	if (len < 0) {
		return len;
	}
	if ((size_t)len > n) {
		return TB_DESC_ERR_SHORT;
	}
	if (tb_crc16_ccitt(buf, (size_t)len - 2u) != rd16(&buf[len - 2])) {
		return TB_DESC_ERR_CRC;
	}
	tb_desc_init(&d);
	d.major = buf[4];
	d.minor = buf[5];
	d.length = (uint16_t)len;
	d.type = buf[8];
	d.rev = (char)buf[9];
	if (d.rev < 'A' || d.rev > 'Z') {
		return TB_DESC_ERR_VALUE;
	}
	d.flags = rd16(&buf[10]);
	d.serial = rd32(&buf[12]);
	d.i3v3_ma = rd16(&buf[16]);
	d.i5v_ma = rd16(&buf[18]);
	d.c3v3_uf = rd16(&buf[20]);
	d.c5v_uf = rd16(&buf[22]);
	pos = TB_DESC_HEADER_LEN;
	while (pos < (size_t)len - 2u) {
		uint8_t type, rlen;
		int err;

		if (pos + 2u > (size_t)len - 2u) {
			return TB_DESC_ERR_RECORD;
		}
		type = buf[pos];
		rlen = buf[pos + 1];
		if (pos + 2u + rlen > (size_t)len - 2u) {
			return TB_DESC_ERR_RECORD;
		}
		err = parse_record(&d, type, rlen, &buf[pos + 2]);
		if (err != TB_DESC_OK) {
			return err;
		}
		pos += 2u + rlen;
	}
	*out = d;
	return TB_DESC_OK;
}

static size_t name_len(const char *s)
{
	size_t n = 0;

	while (n <= TB_DESC_NAME_MAX && s[n] != '\0') {
		n++;
	}
	return n;
}

struct writer {
	uint8_t *buf;
	size_t cap;
	size_t pos;
	bool full;
};

static uint8_t *rec(struct writer *w, uint8_t type, uint8_t len)
{
	uint8_t *p;

	/* Leave room for the CRC. */
	if (w->full || w->pos + 2u + len + 2u > w->cap || w->pos + 2u + len + 2u > TB_DESC_MAX_LEN) {
		w->full = true;
		return NULL;
	}
	p = &w->buf[w->pos];
	p[0] = type;
	p[1] = len;
	w->pos += 2u + len;
	return p + 2;
}

int tb_desc_encode(const struct tb_desc *d, uint8_t *buf, size_t cap)
{
	struct writer w = {.buf = buf, .cap = cap, .pos = TB_DESC_HEADER_LEN};
	uint8_t *p;
	size_t nlen = name_len(d->name);

	if (cap < TB_DESC_MIN_LEN) {
		return TB_DESC_ERR_SPACE;
	}
	if (d->rev < 'A' || d->rev > 'Z' || nlen > TB_DESC_NAME_MAX) {
		return TB_DESC_ERR_VALUE;
	}
	for (size_t i = 0; i < nlen; i++) {
		if (d->name[i] < 0x20 || d->name[i] > 0x7E) {
			return TB_DESC_ERR_VALUE;
		}
	}
	buf[0] = TB_DESC_MAGIC0;
	buf[1] = TB_DESC_MAGIC1;
	buf[2] = TB_DESC_MAGIC2;
	buf[3] = TB_DESC_MAGIC3;
	buf[4] = TB_DESC_MAJOR;
	buf[5] = TB_DESC_MINOR;
	buf[8] = d->type;
	buf[9] = (uint8_t)d->rev;
	wr16(&buf[10], d->flags);
	wr32(&buf[12], d->serial);
	wr16(&buf[16], d->i3v3_ma);
	wr16(&buf[18], d->i5v_ma);
	wr16(&buf[20], d->c3v3_uf);
	wr16(&buf[22], d->c5v_uf);
	if (nlen > 0) {
		p = rec(&w, TB_DESC_REC_NAME, (uint8_t)nlen);
		if (p != NULL) {
			memcpy(p, d->name, nlen);
		}
	}
	for (uint8_t i = 0; i < 4; i++) {
		const struct tb_desc_lane *l = &d->lane[i];

		if (!l->present) {
			continue;
		}
		p = rec(&w, TB_DESC_REC_LANE, 10);
		if (p != NULL) {
			p[0] = i;
			p[1] = l->flags;
			wr16(&p[2], l->r_src_ohm);
			wr16(&p[4], l->cload_pf);
			wr16(&p[6], l->expect_q16);
			wr16(&p[8], l->tol_q16);
		}
	}
	for (uint8_t i = 0; i < 6; i++) {
		if (d->gline_role[i] == TB_G_UNUSED) {
			continue;
		}
		p = rec(&w, TB_DESC_REC_GLINE, 3);
		if (p != NULL) {
			p[0] = i;
			p[1] = d->gline_role[i];
			p[2] = d->gline_arg[i];
		}
	}
	for (uint8_t i = 0; i < d->n_i2c && i < TB_DESC_MAX_I2C; i++) {
		p = rec(&w, TB_DESC_REC_I2C, 2);
		if (p != NULL) {
			p[0] = d->i2c[i].addr;
			p[1] = d->i2c[i].kind;
		}
	}
	for (uint8_t i = 0; i < d->n_spi && i < TB_DESC_MAX_SPI; i++) {
		p = rec(&w, TB_DESC_REC_SPI, 6);
		if (p != NULL) {
			p[0] = d->spi[i].cs;
			p[1] = d->spi[i].mode;
			wr32(&p[2], d->spi[i].max_hz);
		}
	}
	if (d->slot_mask != TB_DESC_ALL_SLOTS && d->slot_mask != 0) {
		p = rec(&w, TB_DESC_REC_SLOTS, 1);
		if (p != NULL) {
			p[0] = d->slot_mask;
		}
	}
	for (uint8_t i = 0; i < TB_DESC_MAX_LOADS; i++) {
		const struct tb_desc_load *ld = &d->load[i];

		if (!ld->present) {
			continue;
		}
		p = rec(&w, TB_DESC_REC_LOAD, 7);
		if (p != NULL) {
			p[0] = i;
			p[1] = ld->gline;
			p[2] = ld->rail;
			p[3] = ld->kind;
			wr16(&p[4], ld->r_mohm);
			p[6] = ld->slot_mask == TB_DESC_ALL_SLOTS ? 0 : ld->slot_mask;
		}
	}
	for (uint8_t i = 0; i < d->n_cal && i < TB_DESC_MAX_CAL; i++) {
		p = rec(&w, TB_DESC_REC_CAL, 6);
		if (p != NULL) {
			wr16(&p[0], d->cal[i].key);
			wr32(&p[2], (uint32_t)d->cal[i].value);
		}
	}
	if (w.full) {
		return TB_DESC_ERR_SPACE;
	}
	wr16(&buf[6], (uint16_t)(w.pos + 2u));
	wr16(&buf[w.pos], tb_crc16_ccitt(buf, w.pos));
	return (int)(w.pos + 2u);
}

const char *tb_desc_check_slot(const struct tb_desc *d, int slot, uint32_t rule3v3_ma, uint32_t rule5v_ma)
{
	if (slot < 1 || slot > 5) {
		return "bad_slot";
	}
	if (!(d->slot_mask & (1u << (slot - 1)))) {
		return "slot_not_allowed";
	}
	if ((d->flags & TB_DESC_F_WIDE) && slot < 4) {
		return "wide_coupon";
	}
	if (d->i3v3_ma > rule3v3_ma) {
		return "over_3v3_rule";
	}
	if (d->i5v_ma > rule5v_ma) {
		return "over_5v_rule";
	}
	return NULL;
}

const char *tb_coupon_type_str(uint8_t type)
{
	switch (type) {
	case TB_COUPON_NONE: return "none";
	case TB_COUPON_TEST: return "test";
	case TB_COUPON_HALL: return "hall";
	case TB_COUPON_TMR: return "tmr";
	case TB_COUPON_SHEAR: return "shear";
	case TB_COUPON_COIL: return "coil";
	case TB_COUPON_HAPTICS: return "haptics";
	case TB_COUPON_KVM: return "kvm";
	default: return "unknown";
	}
}

const char *tb_desc_err_str(int err)
{
	switch (err) {
	case TB_DESC_OK: return "ok";
	case TB_DESC_ERR_SHORT: return "short";
	case TB_DESC_ERR_BLANK: return "blank";
	case TB_DESC_ERR_MAGIC: return "magic";
	case TB_DESC_ERR_VERSION: return "version";
	case TB_DESC_ERR_LENGTH: return "length";
	case TB_DESC_ERR_CRC: return "crc";
	case TB_DESC_ERR_RECORD: return "record";
	case TB_DESC_ERR_VALUE: return "value";
	case TB_DESC_ERR_DUP: return "duplicate";
	case TB_DESC_ERR_FULL: return "full";
	case TB_DESC_ERR_SPACE: return "space";
	default: return "?";
	}
}
