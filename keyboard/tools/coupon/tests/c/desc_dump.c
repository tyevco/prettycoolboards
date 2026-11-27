/*
 * desc_dump: read a coupon descriptor image with coupon_desc.h, the way firmware would, and print what it sees.
 * Built and run by tests/test_c_header.py on the host (gcc), linked with Zephyr v4.5.0's subsys/crc/crc32_sw.c.
 *
 * usage: desc_dump IMAGE.bin      -> "status=<n>" then one "key=value" line per field (status 0 only)
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <string.h>

#include "coupon_desc.h"

int main(int argc, char **argv)
{
	uint8_t buf[COUPON_DESC_SIZE + 16];
	struct coupon_desc d;
	size_t n;
	FILE *f;
	int st, i;

	if (argc != 2 || (f = fopen(argv[1], "rb")) == NULL) {
		fprintf(stderr, "usage: desc_dump IMAGE\n");
		return 2;
	}
	n = fread(buf, 1, sizeof(buf), f);
	fclose(f);
	st = coupon_desc_validate(buf, n);
	printf("status=%d\n", st);
	if (st != COUPON_DESC_OK) {
		return 0;
	}
	memcpy(&d, buf, sizeof(d));
	printf("fmt=%u.%u\nlength=%u\ntype=%u\nrev=%c\nsize=%u\ndefault_slot=%u\nslot_mask=0x%02X\n",
	       d.fmt_major, d.fmt_minor, d.length, d.coupon_type, d.coupon_rev, d.size_class, d.default_slot,
	       d.slot_mask);
	printf("flags=0x%02X\nneeds=0x%04X\nserial=%u\ndate=%u\nuses=0x%08X\n", d.flags, d.needs, d.serial, d.date,
	       d.uses);
	printf("git=");
	for (i = 0; i < 8; i++) {
		printf("%02x", d.git_hash[i]);
	}
	printf("\nspi_max_khz=%u\ni2c_max_khz=%u\nselect=%u,%u,%u\n", d.spi_max_khz, d.i2c_max_khz,
	       d.select_scheme, d.select_steps, d.select_settle_ns);
	for (i = 0; i < 2; i++) {
		printf("rail%d=%u,%u,%u,%u\n", i, d.rails[i].typ_ma, d.rails[i].max_ma, d.rails[i].bulk_uf_x10,
		       d.rails[i].startup_ms);
	}
	for (i = 0; i < 4; i++) {
		printf("lane%d=%u,0x%02X,%u,%u,%u,%u,%.9g,%.9g\n", i, d.lanes[i].kind, d.lanes[i].flags,
		       d.lanes[i].sites, d.lanes[i].unit, d.lanes[i].r_src_ohm, d.lanes[i].cload_max_pf,
		       (double)d.lanes[i].offset, (double)d.lanes[i].gain);
	}
	for (i = 0; i < 6; i++) {
		printf("gline%d=%u,%u,0x%02X\n", i, d.glines[i].role, d.glines[i].arg, d.glines[i].flags);
	}
	for (i = 0; i < 2; i++) {
		printf("cs%d=%u,%u,0x%02X\n", i, d.cs[i].role, d.cs[i].device, d.cs[i].flags);
	}
	for (i = 0; i < COUPON_DESC_MAX_DEVICES; i++) {
		printf("dev%d=0x%04X,%u,0x%02X,%u,%u,0x%02X,%u\n", i, d.devices[i].part, d.devices[i].bus,
		       d.devices[i].addr, d.devices[i].count, d.devices[i].irq, d.devices[i].flags,
		       d.devices[i].spi_mode);
	}
	printf("ext=%u,0x%02X,", d.ext_format, d.ext_flags);
	for (i = 0; i < 32; i++) {
		printf("%02x", d.ext[i]);
	}
	printf("\ncrc=0x%08X\n", d.crc32);
	return 0;
}
