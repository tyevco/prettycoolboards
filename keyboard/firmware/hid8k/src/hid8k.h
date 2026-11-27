/*
 * hid8k: the paced HID stream and its firmware-side statistics.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HID8K_H_
#define HID8K_H_

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/usb/usbd.h>

/* Completion-interval histogram: 12.5 us buckets from 0 to 500 us, then one overflow bucket. */
#define HID8K_HIST_BUCKET_US_X10 125U
#define HID8K_HIST_BUCKETS       40U
#define HID8K_HIST_SLOTS         (HID8K_HIST_BUCKETS + 1U)

/* Statistics over one window (between two snapshots) or since boot / the last reset. */
struct hid8k_stats {
	uint32_t completions;  /* input_report_done callbacks while streaming */
	uint32_t intervals;    /* completion-to-completion intervals measured */
	uint64_t interval_sum; /* cycles */
	uint32_t interval_min; /* cycles */
	uint32_t interval_max; /* cycles */
	uint32_t late;         /* intervals > 1.5 x 125 us */
	uint32_t hist[HID8K_HIST_SLOTS];
	uint32_t submits;      /* successful hid_device_submit_report calls */
	uint64_t cost_sum;     /* cycles spent in those calls */
	uint32_t cost_min;
	uint32_t cost_max;
	uint32_t refused;      /* calls that returned an error */
	uint32_t busy;         /* wanted to submit but could not: no free buffer, or suspended */
	uint32_t kbd;          /* keyboard reports submitted */
};

/* What the stats thread gets each time it looks. */
struct hid8k_snapshot {
	struct hid8k_stats win; /* since the previous snapshot */
	struct hid8k_stats cum; /* since boot or the last reset */
	uint32_t cycles;        /* DWT CYCCNT when the snapshot was taken */
	int64_t uptime_ms;      /* k_uptime_get() at the same moment, to cross-check CYCCNT */
	uint32_t next_seq;
	uint32_t outstanding;   /* reports submitted and not yet completed */
	uint32_t kicks;         /* times the refill kick found the queue empty, since boot */
	int last_err;           /* last non-zero hid_device_submit_report return */
	bool streaming;         /* the HID interface is in the active configuration */
	bool high_speed;
};

/* Cycle counter frequency (the CPU clock). */
uint32_t hid8k_cpu_hz(void);

/* Start the cycle counter and register the HID device. Call before usbd_init(). */
int hid8k_init(struct usbd_context *uds_ctx);

/*
 * Set the trace and cycle-counter enable bits again (idempotent). A debug probe that
 * connects or detaches can rewrite DEMCR; the stats thread calls this once per period.
 */
void hid8k_cycle_counter_keepalive(void);

/*
 * Ask for a refill of the IN queue from the system work queue: it acts only while
 * streaming, not suspended, and with nothing outstanding (a submit was refused and no
 * completion is left to retry it). Safe to call from any thread.
 */
void hid8k_kick(void);

/* Copy and clear the window; optionally clear the cumulative statistics too. */
void hid8k_take_snapshot(struct hid8k_snapshot *snap, bool reset_cum);

/* Flag carried in each stats report: heavy CDC traffic mode is on. */
void hid8k_set_cdc_heavy(bool heavy);

#endif /* HID8K_H_ */
