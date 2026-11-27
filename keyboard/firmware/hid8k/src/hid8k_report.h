/*
 * hid8k: the HID report layout shared with the host tool.
 *
 * The host-side mirror of this file is host/hid8k_analysis.py (STATS_LAYOUT). Change both
 * together and bump HID8K_FORMAT when a field moves.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HID8K_REPORT_H_
#define HID8K_REPORT_H_

/* Report IDs on the one HID interface. */
#define HID8K_REPORT_ID_KBD   1U /* NKRO keyboard: sent only when the user button changes */
#define HID8K_REPORT_ID_STATS 2U /* vendor-defined stats: one per microframe in the rate test */

/* The vendor collection hidapi opens (on Windows the keyboard collection is OS-exclusive). */
#define HID8K_VENDOR_USAGE_PAGE 0xFF00U
#define HID8K_VENDOR_USAGE      0x01U /* the application collection */
#define HID8K_VENDOR_USAGE_DATA 0x02U /* the 63 data bytes */

/* Keyboard report (ID 1): ID, modifier byte, then a bitmap of usages 0x00..0xDF. */
#define HID8K_NKRO_BITS 224U
#define HID8K_KBD_SIZE  (2U + HID8K_NKRO_BITS / 8U) /* 30 bytes on the wire */
#define HID8K_KEY_F24   0x73U /* Keyboard/Keypad page: F24, harmless on Windows and Linux */

/*
 * Stats report (ID 2): 64 bytes on the wire including the report ID, so the interrupt IN
 * endpoint's wMaxPacketSize stays 64 and usbd_hid uses its simple (no alternate setting)
 * interface. All multi-byte fields are little-endian. "cycles" are DWT CYCCNT counts of
 * the CPU clock (cpu_hz below, 160 MHz on the Nucleo), which wrap every 2^32 cycles.
 */
#define HID8K_STATS_SIZE 64U
#define HID8K_FORMAT     1U

#define HID8K_OFF_ID           0U  /* u8  report ID = 2 */
#define HID8K_OFF_FORMAT       1U  /* u8  HID8K_FORMAT */
#define HID8K_OFF_FLAGS        2U  /* u8  HID8K_FLAG_* */
#define HID8K_OFF_DEPTH        3U  /* u8  reports kept queued (CONFIG_HID8K_QUEUE_DEPTH) */
#define HID8K_OFF_SEQ          4U  /* u32 sequence number of this report; counts every report
				    *     submitted on the IN endpoint, IDs 1 and 2 */
#define HID8K_OFF_T_SUBMIT     8U  /* u32 cycles: just before this report's submit call */
#define HID8K_OFF_DONE_SEQ     12U /* u32 seq of the latest completed report when this one was
				    *     built (with depth 2 it is seq - 2) */
#define HID8K_OFF_T_DONE       16U /* u32 cycles: that completion's input_report_done callback */
#define HID8K_OFF_SUBMIT_COST  20U /* u32 cycles taken by the previous submit call */
#define HID8K_OFF_REFUSED      24U /* u32 submit calls that returned an error, since boot */
#define HID8K_OFF_BUSY         28U /* u32 times a submit was wanted but not made (no free report
				    *     buffer, or the bus still marked suspended), since boot */
#define HID8K_OFF_LATE         32U /* u32 completion intervals > 1.5 x 125 us, since boot */
#define HID8K_OFF_KBD_COUNT    36U /* u32 keyboard reports (ID 1) submitted, since boot */
#define HID8K_OFF_CPU_HZ       40U /* u32 the cycle counter's frequency */
#define HID8K_OFF_FN_DONE      44U /* u16 OTG_HS DSTS.FNSOF read in that completion callback,
				    *     valid only with HID8K_FLAG_FN_VALID */
#define HID8K_OFF_FN_SUBMIT    46U /* u16 the same register read at this report's submit */
#define HID8K_OFF_MAX_INTERVAL 48U /* u32 cycles: longest completion interval since reset */
#define HID8K_OFF_UPTIME_MS    52U /* u32 k_uptime_get_32() at build */
#define HID8K_OFF_CDC_BYTES    56U /* u32 bytes queued to the CDC console, since boot */
#define HID8K_OFF_CDC_DROPPED  60U /* u32 bytes dropped because the CDC ring was full */

#define HID8K_FLAG_FN_VALID   0x01U /* CONFIG_HID8K_FRAME_NUMBER=y: FN fields are meaningful */
#define HID8K_FLAG_CDC_HEAVY  0x02U /* heavy CDC traffic mode was on when built */
#define HID8K_FLAG_HIGH_SPEED 0x04U /* the bus enumerated at high speed */

/* Completion intervals above this many microseconds x 10 count as late (1.5 x 125 us). */
#define HID8K_NOMINAL_US      125U
#define HID8K_LATE_US_X10     1875U

#endif /* HID8K_REPORT_H_ */
