/*
 * Host fuzz of the coupon descriptor parser (tb/desc.h) under ASan and UBSan: noise, and the test coupon's real
 * descriptor with random bytes changed (its CRC recomputed in both byte orders, or not), some of it truncated.
 * The parser must never crash, overread or invoke undefined behaviour, and whatever it accepts must survive
 * encode -> parse -> encode byte for byte. A coupon's EEPROM is input the firmware does not control (blank,
 * corrupted, written by another tool), so this is the parser's contract. Run by test_fuzz_desc.py.
 *
 *   gcc -std=c11 -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -Iinclude  *       tools/fuzz_desc.c src/desc.c src/desc_test_coupon.c src/rails.c -o <scratch>/fuzz_desc
 *   <scratch>/fuzz_desc 3000000
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tb/desc.h"

static uint32_t x = 2463534242u;
static uint32_t rnd(void) { x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x; }

int main(int argc, char **argv)
{
	long iters = argc > 1 ? atol(argv[1]) : 2000000;
	struct tb_desc d, good;
	uint8_t base[TB_DESC_MAX_LEN], buf[TB_DESC_MAX_LEN + 64];
	int ok = 0, err = 0, enc;

	tb_desc_test_coupon(&good, 7);
	enc = tb_desc_encode(&good, base, sizeof(base));
	if (enc <= 0) { printf("encode failed %d\n", enc); return 1; }
	for (long i = 0; i < iters; i++) {
		size_t n;
		int mode = rnd() % 4;
		if (mode == 0) {           /* pure noise */
			n = rnd() % sizeof(buf);
			for (size_t k = 0; k < n; k++) buf[k] = rnd();
		} else {                   /* a valid descriptor, mutated, CRC fixed up or not */
			n = (size_t)enc;
			memcpy(buf, base, n);
			int flips = 1 + rnd() % 8;
			for (int f = 0; f < flips; f++) buf[rnd() % n] = rnd();
			if (mode >= 2) {       /* recompute the CRC so the parser goes past it */
				uint16_t c = tb_crc16_ccitt(buf, n - 2);
				buf[n - 2] = c >> 8; buf[n - 1] = c;  /* big- or little-endian: try both */
				if (mode == 3) { buf[n - 2] = c; buf[n - 1] = c >> 8; }
			}
			if (rnd() % 8 == 0) n = rnd() % (n + 1);  /* truncated */
		}
		uint8_t *heap = malloc(n ? n : 1);   /* exact-size heap copy: ASan sees any overread */
		memcpy(heap, buf, n);
		int r = tb_desc_parse(heap, n, &d);
		(void)tb_desc_peek_length(heap, n);
		free(heap);
		if (r == 0) {
			uint8_t e1[TB_DESC_MAX_LEN], e2[TB_DESC_MAX_LEN];
			struct tb_desc d2;
			int n1 = tb_desc_encode(&d, e1, sizeof(e1)), n2;
			ok++;
			if (n1 > 0) {
				if (tb_desc_parse(e1, (size_t)n1, &d2) != 0) { printf("re-parse failed at %ld\n", i); return 2; }
				n2 = tb_desc_encode(&d2, e2, sizeof(e2));
				if (n2 != n1 || memcmp(e1, e2, (size_t)n1)) { printf("round trip differs at %ld\n", i); return 3; }
			}
		} else err++;
	}
	printf("iterations %ld: parsed %d, refused %d\n", iters, ok, err);
	return 0;
}
