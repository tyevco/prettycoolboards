/*
 * tb/desc.h: the coupon descriptor in the M24C02 EEPROM at 0x50 on every coupon (SPEC §4.6).
 *
 * THE FORMAT IS A PROPOSAL. SPEC §4.6 leaves it to compiler v0 (§11 #18: "Define in compiler v0; the test
 * coupon carries the first one"). This is the bring-up firmware's draft of it, version 1.0, to be replaced or
 * confirmed by the compiler. It carries what SPEC §4.6 lists: format version, coupon type and revision, serial,
 * the rails it needs and their limits, the lane map with each lane's source impedance and load, the G-line
 * roles, its SPI and I2C devices, and calibration. keyboard/firmware/lib/tools/coupon_desc.py is the reference
 * encoder in Python, and the lib's tests decode its output.
 *
 * Layout, little-endian, at most 256 bytes (the M24C02's 2 kbit):
 *
 *   0  4  magic "PCKD"
 *   4  1  format major (1): a reader refuses another major
 *   5  1  format minor (0): a reader accepts any minor of its major and skips record types it does not know
 *   6  2  length L of the whole descriptor including the CRC, 26 <= L <= 256
 *   8  1  coupon type (enum tb_coupon_type)
 *   9  1  coupon revision, an ASCII capital ('A')
 *  10  2  flags (TB_DESC_F_*)
 *  12  4  serial
 *  16  2  +3V3: the most the coupon draws, mA (the budget's declared current; SPEC §4.9 rule 250 mA)
 *  18  2  +5V: the most it draws, mA; 0 = it does not want +5V (rule 500 mA, S5 2 A)
 *  20  2  +3V3 bulk capacitance, uF (rule <= 47)
 *  22  2  +5V bulk capacitance, uF (rule <= 100, S5 470)
 *  24  ..  records: type u8, length u8, value[length]
 *  L-2 2  CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final XOR) over bytes 0 .. L-3
 *
 * Records (type: value):
 *   0x01 NAME   1-32 printable ASCII bytes
 *   0x02 LANE   lane u8 (0-3), flags u8 (TB_LANE_F_*), R_src ohm u16, C_load max pF u16,
 *               expected ratio of the coupon's +3V3 u16 (Q16: 0.2 = 13107; 0 = none), tolerance u16 (Q16)
 *   0x03 GLINE  line u8 (0-5), role u8 (enum tb_gline_role), argument u8
 *   0x04 I2C    7-bit address u8, kind u8 (enum tb_i2c_kind)
 *   0x05 SPI    chip select u8 (0, 1), mode u8 (0-3), max clock Hz u32
 *   0x06 SLOTS  allowed slots u8 (bit n-1 = slot n)
 *   0x07 LOAD   index u8 (0-3), G-line u8, rail u8 (0 = +3V3, 1 = +5V), kind u8 (0 calibration, 1 current
 *               limit), resistance mOhm u16, allowed slots u8
 *   0x08 CAL    key u16, value s32
 *   0x00 PAD    (any length) ignored
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_DESC_H_
#define TB_DESC_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TB_DESC_MAGIC0 'P'
#define TB_DESC_MAGIC1 'C'
#define TB_DESC_MAGIC2 'K'
#define TB_DESC_MAGIC3 'D'
#define TB_DESC_MAJOR 1
#define TB_DESC_MINOR 0
#define TB_DESC_HEADER_LEN 24
#define TB_DESC_MIN_LEN (TB_DESC_HEADER_LEN + 2)
#define TB_DESC_MAX_LEN 256
#define TB_DESC_EEPROM_PAGE 16  /* M24C02 page size, bytes */

#define TB_DESC_F_WIDE    (1u << 0) /* the 80 mm wide coupon (S4, S5 only) */
#define TB_DESC_F_SENSORS (1u << 1) /* carries sensors (the test coupon does not) */

#define TB_LANE_F_USED        (1u << 0)
#define TB_LANE_F_RATIOMETRIC (1u << 1)
#define TB_LANE_F_BUFFERED    (1u << 2)

#define TB_DESC_REC_PAD   0x00
#define TB_DESC_REC_NAME  0x01
#define TB_DESC_REC_LANE  0x02
#define TB_DESC_REC_GLINE 0x03
#define TB_DESC_REC_I2C   0x04
#define TB_DESC_REC_SPI   0x05
#define TB_DESC_REC_SLOTS 0x06
#define TB_DESC_REC_LOAD  0x07
#define TB_DESC_REC_CAL   0x08

#define TB_DESC_NAME_MAX 32
#define TB_DESC_MAX_I2C 8
#define TB_DESC_MAX_SPI 2
#define TB_DESC_MAX_LOADS 4
#define TB_DESC_MAX_CAL 8
#define TB_DESC_ALL_SLOTS 0x1Fu

enum tb_coupon_type {
	TB_COUPON_NONE = 0,
	TB_COUPON_TEST = 1,
	TB_COUPON_HALL = 2,
	TB_COUPON_TMR = 3,
	TB_COUPON_SHEAR = 4,
	TB_COUPON_COIL = 5,
	TB_COUPON_HAPTICS = 6,
	TB_COUPON_KVM = 7,
};

enum tb_gline_role {
	TB_G_UNUSED = 0,
	TB_G_SELECT = 1,   /* argument: select bit */
	TB_G_SELECT_EN = 2,
	TB_G_ENABLE = 3,
	TB_G_ADDR = 4,     /* an address strap (argument: device index) */
	TB_G_LOAD = 5,     /* argument: load index */
	TB_G_LED = 6,
	TB_G_IRQ_TEST = 7, /* drives IRQ_N low while high */
	TB_G_PWM = 8,
	TB_G_RESET = 9,
	TB_G_CS = 10,      /* an extra chip select */
};

enum tb_i2c_kind {
	TB_I2C_OTHER = 0,
	TB_I2C_EEPROM = 1,
	TB_I2C_LDC1614 = 2,
	TB_I2C_DRV2605L = 3,
	TB_I2C_EXPANDER = 4,
	TB_I2C_TOUCH = 5,
};

enum tb_desc_err {
	TB_DESC_OK = 0,
	TB_DESC_ERR_SHORT = -1,   /* fewer bytes than the header, or than the length says */
	TB_DESC_ERR_BLANK = -2,   /* erased EEPROM: the first bytes all 0xFF */
	TB_DESC_ERR_MAGIC = -3,
	TB_DESC_ERR_VERSION = -4, /* a major this reader does not know */
	TB_DESC_ERR_LENGTH = -5,
	TB_DESC_ERR_CRC = -6,
	TB_DESC_ERR_RECORD = -7,  /* a record runs past the end, or has the wrong length */
	TB_DESC_ERR_VALUE = -8,   /* a lane, G-line, CS, mode or index out of range, a bad name or revision */
	TB_DESC_ERR_DUP = -9,     /* the same lane, G-line or load twice */
	TB_DESC_ERR_FULL = -10,   /* more I2C, SPI, load or CAL records than this reader keeps */
	TB_DESC_ERR_SPACE = -11,  /* encode: does not fit */
};

struct tb_desc_lane {
	bool present;
	uint8_t flags;
	uint16_t r_src_ohm;
	uint16_t cload_pf;
	uint16_t expect_q16;
	uint16_t tol_q16;
};

struct tb_desc_load {
	bool present;
	uint8_t gline;
	uint8_t rail; /* 0 = +3V3, 1 = +5V */
	uint8_t kind; /* 0 calibration, 1 current limit */
	uint16_t r_mohm;
	uint8_t slot_mask;
};

struct tb_desc {
	uint8_t major, minor;
	uint16_t length;
	uint8_t type;
	char rev;
	uint16_t flags;
	uint32_t serial;
	uint16_t i3v3_ma, i5v_ma, c3v3_uf, c5v_uf;
	char name[TB_DESC_NAME_MAX + 1];
	struct tb_desc_lane lane[4];
	uint8_t gline_role[6];
	uint8_t gline_arg[6];
	uint8_t n_i2c;
	struct {
		uint8_t addr, kind;
	} i2c[TB_DESC_MAX_I2C];
	uint8_t n_spi;
	struct {
		uint8_t cs, mode;
		uint32_t max_hz;
	} spi[TB_DESC_MAX_SPI];
	uint8_t slot_mask; /* TB_DESC_ALL_SLOTS when no SLOTS record */
	struct tb_desc_load load[TB_DESC_MAX_LOADS];
	uint8_t n_cal;
	struct {
		uint16_t key;
		int32_t value;
	} cal[TB_DESC_MAX_CAL];
	uint8_t n_unknown; /* records of a type this reader skipped */
};

uint16_t tb_crc16_ccitt(const uint8_t *data, size_t len);

/* The length the header declares, or a negative tb_desc_err (for reading the rest of the EEPROM). */
int tb_desc_peek_length(const uint8_t *buf, size_t n);
int tb_desc_parse(const uint8_t *buf, size_t n, struct tb_desc *out);
/* Encode d (its length field is ignored) into buf; returns the length or a negative tb_desc_err. */
int tb_desc_encode(const struct tb_desc *d, uint8_t *buf, size_t cap);
void tb_desc_init(struct tb_desc *d);

/* The test coupon's descriptor (keyboard/hardware/design/sheets/test_coupon.py), as tools/coupon_desc.py's
 * test_coupon() builds it; the lib's tests check the two encode to the same bytes. */
void tb_desc_test_coupon(struct tb_desc *d, uint32_t serial);

/* Coupon rules against one slot (SPEC §4.9): 0, or the first broken rule as a short token. */
const char *tb_desc_check_slot(const struct tb_desc *d, int slot, uint32_t rule3v3_ma, uint32_t rule5v_ma);

const char *tb_coupon_type_str(uint8_t type);
const char *tb_desc_err_str(int err);

#ifdef __cplusplus
}
#endif

#endif /* TB_DESC_H_ */
