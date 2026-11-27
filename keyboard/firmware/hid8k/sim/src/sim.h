/*
 * hid8k-sim: what the host-side files share. Everything here runs in cooperative threads (the
 * USB host stack's "usbh" thread for transfer completions, and the test thread), which never
 * interleave on native_sim's single CPU unless one blocks, so plain variables are enough.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HID8K_SIM_H_
#define HID8K_SIM_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/usb/usbh.h>

/* The host controller and its context (sim_main.c). */
extern struct usbh_context *const sim_uhs_ctx;

/*
 * The test's own output: straight to the host's stdout (nsi_print_trace()), not through the
 * firmware's deferred log buffer, which drops messages when a burst outruns it. The firmware's
 * printk() and log messages still go through Zephyr's logging, as on the board, so they can
 * appear a little later than the test's lines.
 */
void sim_print(const char *fmt, ...) __printf_like(1, 2);

/* Simulated time, microseconds (native_sim: 1 MHz cycles and ticks). */
int64_t sim_now_us(void);

/* Report an anomaly seen by a class driver: printed (the first ones) and counted. */
void sim_anomaly(const char *fmt, ...);
uint32_t sim_anomalies(void);

/* ------------------------------------------------------------------ HID host class (host_hid.c) */

struct sim_hid_info {
	bool bound;
	uint8_t iface;
	uint8_t if_class, if_sub, if_proto, if_num_ep;
	uint16_t bcd_hid;
	uint8_t rdesc_type;
	uint16_t rdesc_len;
	uint8_t ep;          /* bEndpointAddress of the interrupt IN endpoint */
	uint8_t ep_attr;     /* bmAttributes */
	uint16_t ep_mps;     /* wMaxPacketSize */
	uint8_t ep_interval; /* bInterval */
	uint32_t binds;      /* times the class was bound (1 per enumeration) */
	uint32_t removals;
};

/* Stream checks, kept by the completion callback for every report. */
struct sim_hid_stats {
	uint32_t transfers;   /* completed IN transfers with data */
	uint32_t stats;       /* stats reports (ID 2) */
	uint32_t kbd;         /* keyboard reports (ID 1) */
	uint32_t kbd_f24_down;
	uint32_t kbd_f24_up;
	uint32_t bad;         /* wrong length, ID, format, depth, cpu_hz, flags */
	uint32_t xfer_err;    /* transfers that ended with an error other than a cancellation */
	uint32_t cancelled;
	uint32_t zero_len;
	uint32_t per_slot[2]; /* completed transfers per queued-transfer slot (HOST_XFERS) */
	uint32_t seq_breaks;  /* a report whose seq is not the previous one + 1 */
	uint32_t lag_short;   /* seq - done_seq below the depth: the queue was refilled from empty */
	uint32_t lag_bad;     /* seq - done_seq of 0 or above the depth: should never happen */
	uint32_t first_seq, last_seq;
	uint32_t first_done_seq; /* done_seq of the first stats report since the last clear */
	/* Device completion intervals from t_done, cycles: consecutive done_seq only. */
	uint32_t ival_n, ival_min, ival_max;
	uint64_t ival_sum;
	/* Host arrival minus t_submit (the same clock in the simulation), cycles. */
	uint32_t age_min, age_max;
	/* Host arrival intervals, us. */
	uint32_t gap_n;
	int64_t gap_min_us, gap_max_us;
	int64_t last_arrival_us;
	/* The latest stats report's counters. */
	uint32_t refused, busy, late, kbd_count, uptime_ms, cdc_bytes, cdc_dropped;
	uint8_t flags;
};

bool sim_hid_bound(void);
const struct sim_hid_info *sim_hid_info(void);
struct usb_device *sim_hid_udev(void);
/* Start or stop polling. Stopping lets the transfer in flight finish and queues no more. */
int sim_hid_poll(bool on);
bool sim_hid_polling(void);
/* Copy the statistics; clear them if asked (the stream checks continue across a clear). */
void sim_hid_stats(struct sim_hid_stats *out, bool clear);
/* Forget the previous report: the next one starts a new stream (after a reconnect). */
void sim_hid_stream_restart(void);
/* Capture every report to the host file (fd from nsi_host_open), or stop with -1. */
void sim_hid_capture(int fd);
uint32_t sim_hid_captured(void);
void sim_hid_capture_flush(void);

/* ------------------------------------------------------------ CDC ACM host class (host_cdc.c) */

struct sim_cdc_info {
	bool bound;
	uint8_t comm_iface, data_iface;
	uint8_t iad_class, iad_sub, iad_proto;
	uint8_t ep_notify, ep_in, ep_out;
	uint16_t mps_in, mps_out, mps_notify;
	uint8_t notify_interval;
	uint32_t binds;
	uint32_t removals;
};

struct sim_cdc_stats {
	uint32_t rx_bytes;
	uint32_t rx_transfers;
	uint32_t zlp;
	uint32_t lines;        /* complete lines received, filler included */
	uint32_t stats_lines;  /* lines starting "hid8k t=" */
	uint32_t fill_lines;
	uint32_t fill_breaks;  /* a filler line whose number is not the previous one + 1 */
	uint32_t fill_missing; /* filler lines missing at those breaks */
	uint32_t fill_bad;     /* a filler line of the wrong length or form */
	uint32_t line_bad;     /* another line that is not a whole firmware line (see host_cdc.c) */
	uint32_t tx_bytes;
	uint32_t xfer_err;
};

bool sim_cdc_bound(void);
const struct sim_cdc_info *sim_cdc_info(void);
/* Start reading the bulk IN endpoint. */
int sim_cdc_start(void);
/*
 * Stop reading it, as a host with the port closed does: the transfer in flight completes, no
 * more are queued, so the device's CDC buffers and the firmware's ring fill up.
 */
void sim_cdc_stop(void);
/* Send a command line (CR LF added) on the bulk OUT endpoint. */
int sim_cdc_send(const char *line);
void sim_cdc_stats(struct sim_cdc_stats *out);
/* Lines are numbered from 0 as they arrive (filler lines are counted, not kept). */
uint32_t sim_cdc_line_count(void);
/*
 * Find the first kept line at or after number *from that contains needle; copy it to out and set
 * *from past it. Lines older than the ring are gone.
 */
bool sim_cdc_find(uint32_t *from, const char *needle, char *out, size_t out_len);
/*
 * The same, also giving the byte count of the CDC stream (since the reader started) at the end
 * of that line, its CR LF included.
 */
bool sim_cdc_find_at(uint32_t *from, const char *needle, char *out, size_t out_len,
		     uint32_t *bytes_end);
/* Log every received byte to the host file (fd from nsi_host_open), or stop with -1. */
void sim_cdc_log(int fd);

#endif /* HID8K_SIM_H_ */
