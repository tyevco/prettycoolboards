/*
 * Coupon descriptor EEPROM access (see descio.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>

#include "board.h"
#include "descio.h"

#define CHUNK 32
#define WRITE_POLL_MS 10 /* the M24C02's write cycle is 5 ms max */

static int read_at(const struct device *bus, uint8_t addr, uint8_t *buf, size_t n)
{
	return i2c_write_read(bus, TB_I2C_ADDR_DESCRIPTOR, &addr, 1, buf, n);
}

int tb_descio_read(int slot, uint8_t *buf, size_t cap, size_t *len)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	size_t want = CHUNK, got = 0;
	int err, plen;

	*len = 0;
	if (h == NULL || cap < CHUNK) {
		return -EINVAL;
	}
	err = read_at(h->i2c_ch, 0, buf, CHUNK);
	if (err != 0) {
		return err;
	}
	got = CHUNK;
	plen = tb_desc_peek_length(buf, got);
	if (plen > 0) {
		want = MIN((size_t)plen, cap);
	}
	while (got < want) {
		size_t n = MIN((size_t)CHUNK, want - got);

		err = read_at(h->i2c_ch, (uint8_t)got, &buf[got], n);
		if (err != 0) {
			return err;
		}
		got += n;
	}
	*len = got;
	return 0;
}

int tb_descio_load(int slot, uint8_t *raw, size_t cap, size_t *len)
{
	int err = tb_descio_read(slot, raw, cap, len);
	int perr;

	if (err != 0) {
		tb.desc_err[slot - 1] = TB_DESCIO_BUS_ERR;
		return TB_DESCIO_BUS_ERR;
	}
	perr = tb_desc_parse(raw, *len, &tb.desc[slot - 1]);
	tb.desc_err[slot - 1] = perr;
	return perr;
}

int tb_descio_write(int slot, const uint8_t *buf, size_t len)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	uint8_t page[1 + TB_DESC_EEPROM_PAGE];

	if (h == NULL || len > TB_DESC_MAX_LEN) {
		return -EINVAL;
	}
	for (size_t off = 0; off < len; off += TB_DESC_EEPROM_PAGE) {
		size_t n = MIN((size_t)TB_DESC_EEPROM_PAGE, len - off);
		int64_t until;
		int err;

		page[0] = (uint8_t)off; /* page-aligned: a page write never rolls over */
		memcpy(&page[1], &buf[off], n);
		err = i2c_write(h->i2c_ch, page, 1 + n, TB_I2C_ADDR_DESCRIPTOR);
		if (err != 0) {
			return err;
		}
		/* ACK polling: the device does not acknowledge its address during the write cycle. */
		until = k_uptime_get() + WRITE_POLL_MS;
		do {
			k_msleep(1);
			err = i2c_write(h->i2c_ch, page, 1, TB_I2C_ADDR_DESCRIPTOR);
		} while (err != 0 && k_uptime_get() < until);
		if (err != 0) {
			return -ETIMEDOUT;
		}
	}
	return 0;
}
