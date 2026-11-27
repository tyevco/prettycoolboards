/*
 * coupon_desc.h under Zephyr v4.5.0 on native_sim (tests/test_zephyr_app.py builds and runs this).
 *
 * direct build (direct.overlay): an emulated M24C02-geometry EEPROM on the emulated I2C bus, driven by Zephyr's own
 *   eeprom_at2x driver: it starts erased (0xFF), the image make_eeprom.py made is written through eeprom_write()
 *   (the driver splits it at 16-byte pages), read back in one eeprom_read(), and checked with
 *   coupon_desc_validate(), which uses Zephyr's crc32_ieee() (CONFIG_CRC).
 * mux build (mux.overlay + mux.conf): the slot mux and five EEPROMs at 0x50 behind it; checks that every EEPROM device
 *   is ready although nothing answers on the bus (the AT24 driver does not touch the chip at init), that an unlabelled
 *   node is named "eeprom@50" and the labelled ones by their label, and how long a read of an absent coupon takes.
 *
 * Nothing here is hardware: the emulator is not an M24C02 (no write cycle time, no page roll-over).
 * SPDX-License-Identifier: Apache-2.0
 */
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/eeprom.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/ztest.h>

#include "coupon_desc.h"
#include "coupon_image.inc" /* coupon_image[], COUPON_IMAGE_* expected values: written by the test */

#if DT_NODE_EXISTS(DT_NODELABEL(coupon_ee))

static const struct device *const ee = DEVICE_DT_GET(DT_NODELABEL(coupon_ee));

ZTEST(coupon_direct, test_blank_then_written)
{
	uint8_t buf[COUPON_DESC_SIZE];
	struct coupon_desc d;

	zassert_true(device_is_ready(ee), "eeprom not ready");
	zassert_equal(eeprom_get_size(ee), COUPON_DESC_SIZE);
	zassert_ok(eeprom_read(ee, 0, buf, sizeof(buf)));
	zassert_equal(coupon_desc_validate(buf, sizeof(buf)), COUPON_DESC_E_BLANK, "a fresh EEPROM is not blank");

	for (size_t off = 0; off < sizeof(coupon_image); off += COUPON_DESC_PAGE_SIZE) {
		zassert_ok(eeprom_write(ee, off, &coupon_image[off], COUPON_DESC_PAGE_SIZE), "page %u", (unsigned)off);
	}
	memset(buf, 0, sizeof(buf));
	zassert_ok(eeprom_read(ee, 0, buf, sizeof(buf)));
	zassert_mem_equal(buf, coupon_image, sizeof(buf));
	zassert_equal(coupon_desc_validate(buf, sizeof(buf)), COUPON_DESC_OK);
	memcpy(&d, buf, sizeof(d));
	zassert_equal(d.coupon_type, COUPON_IMAGE_TYPE);
	zassert_equal(d.serial, COUPON_IMAGE_SERIAL);
	zassert_equal(d.uses, COUPON_IMAGE_USES);
	zassert_equal(d.rails[COUPON_RAIL_3V3].max_ma, COUPON_IMAGE_MAX_MA_3V3);
	zassert_equal(d.rails[COUPON_RAIL_5V].max_ma, COUPON_IMAGE_MAX_MA_5V);
	zassert_equal(d.crc32, COUPON_IMAGE_CRC);
	zassert_equal(crc32_ieee(buf, COUPON_DESC_CRC_OFFSET), COUPON_IMAGE_CRC);
	printk("COUPON direct: type %u serial %u uses 0x%08x crc 0x%08x\n", d.coupon_type, d.serial, d.uses,
	       d.crc32);
}

ZTEST(coupon_direct, test_one_byte_off_fails_crc)
{
	uint8_t buf[COUPON_DESC_SIZE];
	uint8_t b = coupon_image[0x31] ^ 0x01;

	zassert_ok(eeprom_write(ee, 0, coupon_image, 0)); /* a zero-length write is accepted */
	for (size_t off = 0; off < sizeof(coupon_image); off += COUPON_DESC_PAGE_SIZE) {
		zassert_ok(eeprom_write(ee, off, &coupon_image[off], COUPON_DESC_PAGE_SIZE));
	}
	zassert_ok(eeprom_write(ee, 0x31, &b, 1));
	zassert_ok(eeprom_read(ee, 0, buf, sizeof(buf)));
	zassert_equal(coupon_desc_validate(buf, sizeof(buf)), COUPON_DESC_E_CRC);
}

ZTEST(coupon_direct, test_unaligned_write_is_split_at_pages)
{
	uint8_t buf[COUPON_DESC_SIZE];

	/* one call from offset 5 to the end: the driver must write it page by page (it caps each write at the page
	 * boundary), so the result equals the image */
	zassert_ok(eeprom_write(ee, 0, coupon_image, 5));
	zassert_ok(eeprom_write(ee, 5, &coupon_image[5], sizeof(coupon_image) - 5));
	zassert_ok(eeprom_read(ee, 0, buf, sizeof(buf)));
	zassert_mem_equal(buf, coupon_image, sizeof(buf));
}

ZTEST_SUITE(coupon_direct, NULL, NULL, NULL, NULL, NULL);

#if defined(CONFIG_EEPROM_SHELL)
#include <zephyr/shell/shell.h>
#include <zephyr/shell/shell_dummy.h>
#include <zephyr/sys/util.h>

#include "coupon_shell.inc" /* coupon_shell_lines[]: make_eeprom.py --shell coupon-s1, written by the test */

/* The lines make_eeprom.py --shell writes, through Zephyr's own eeprom shell: every one is accepted (3 arguments
 * plus 16 bytes is 20 tokens, CONFIG_SHELL_ARGC_MAX's default), and the EEPROM then holds the image. */
ZTEST(coupon_shell, test_make_eeprom_shell_lines_write_the_image)
{
	const struct shell *sh = shell_backend_dummy_get_ptr();
	uint8_t buf[COUPON_DESC_SIZE];

	WAIT_FOR(shell_ready(sh), 20000, k_msleep(1));
	zassert_true(shell_ready(sh), "dummy shell backend not ready");
	zassert_ok(shell_execute_cmd(sh, "eeprom fill coupon-s1 0 256 0"));
	for (size_t i = 0; i < ARRAY_SIZE(coupon_shell_lines); i++) {
		zassert_ok(shell_execute_cmd(sh, coupon_shell_lines[i]), "%s", coupon_shell_lines[i]);
	}
	zassert_ok(eeprom_read(ee, 0, buf, sizeof(buf)));
	zassert_mem_equal(buf, coupon_image, sizeof(buf));
	zassert_equal(coupon_desc_validate(buf, sizeof(buf)), COUPON_DESC_OK);
	printk("COUPON shell: %u lines accepted, image valid\n", (unsigned)ARRAY_SIZE(coupon_shell_lines));
}

/* No headroom: one byte more per line (21 tokens) is refused by the shell. */
ZTEST(coupon_shell, test_seventeen_bytes_is_one_argument_too_many)
{
	const struct shell *sh = shell_backend_dummy_get_ptr();

	zassert_true(shell_execute_cmd(sh, "eeprom write coupon-s1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17") != 0);
	zassert_ok(shell_execute_cmd(sh, "eeprom write coupon-s1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16"));
}

ZTEST_SUITE(coupon_shell, NULL, NULL, NULL, NULL, NULL);
#endif
#endif

#if DT_NODE_EXISTS(DT_NODELABEL(slot_mux))

#define EE(n) DEVICE_DT_GET(DT_NODELABEL(ee_s##n))
static const struct device *const slot_ee[] = {EE(0), EE(1), EE(2), EE(3), EE(4)};

ZTEST(coupon_mux, test_every_slot_eeprom_is_ready_without_a_chip)
{
	for (int i = 0; i < 5; i++) {
		zassert_true(device_is_ready(slot_ee[i]), "S%d eeprom not ready", i + 1);
	}
}

ZTEST(coupon_mux, test_names)
{
	zassert_str_equal(slot_ee[0]->name, "eeprom@50");
	zassert_str_equal(slot_ee[1]->name, "coupon-s2");
	zassert_str_equal(slot_ee[4]->name, "coupon-s5");
	/* by name, "eeprom@50" can reach only the one unlabelled node; the labelled ones by their label */
	zassert_equal_ptr(device_get_binding("eeprom@50"), slot_ee[0]);
	zassert_equal_ptr(device_get_binding("coupon-s3"), slot_ee[2]);
	printk("COUPON names: %s %s %s %s %s\n", slot_ee[0]->name, slot_ee[1]->name, slot_ee[2]->name,
	       slot_ee[3]->name, slot_ee[4]->name);
}

ZTEST(coupon_mux, test_absent_coupon_read_fails)
{
	uint8_t buf[COUPON_DESC_SIZE];
	int64_t t0 = k_uptime_get();
	int err = eeprom_read(slot_ee[1], 0, buf, sizeof(buf));
	int64_t dt = k_uptime_get() - t0;

	zassert_true(err < 0, "a read with nothing on the bus returned %d", err);
	printk("COUPON absent read: err %d after %lld ms\n", err, dt);
}

ZTEST_SUITE(coupon_mux, NULL, NULL, NULL, NULL, NULL);
#endif
