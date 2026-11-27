/*
 * hid8k-sim: a minimal HID host class driver for Zephyr's USB host stack. Zephyr v4.5.0 has none
 * (subsys/usb/host/class/ holds only a hub and a UVC driver), so this one binds to the HID
 * interface, keeps CONFIG_HID8K_SIM_HOST_XFERS interrupt IN transfers queued (1 by default, the
 * way Linux usbhid keeps one interrupt URB), and checks every report as it arrives:
 *
 *   - the report ID and length (ID 1: 30 bytes; ID 2: 64), the stats format, queue depth,
 *     cycle-counter rate and flags;
 *   - sequence continuity: every report on the endpoint (IDs 1 and 2) takes one seq, so a stats
 *     report's seq must be the previous report's seq + 1;
 *   - the pacing: in steady state a stats report names the completion DEPTH reports before it
 *     (seq - done_seq == CONFIG_HID8K_QUEUE_DEPTH), and consecutive completions are one frame
 *     apart on the device's clock;
 *   - the age of each report when the host takes it (arrival - t_submit; the simulation has one
 *     clock, so this is exact).
 *
 * It can also stop and restart polling, which is how a host that stops reading looks to the
 * device, and capture every report to a host file for host/hid8k_analysis.py.
 *
 * The completion callback runs in the host stack's cooperative "usbh" thread.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <errno.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>
#include <zephyr/usb/class/hid.h>
#include <zephyr/usb/usb_ch9.h>
#include <zephyr/usb/usbh.h>

#include <nsi_host_trampolines.h>

#include <usbh_class.h>
#include <usbh_class_api.h>
#include <usbh_desc.h>
#include <usbh_device.h>

#include "hid8k_report.h"
#include "sim.h"

LOG_MODULE_REGISTER(sim_hid, LOG_LEVEL_INF);

#define DEPTH CONFIG_HID8K_QUEUE_DEPTH
#define NXFERS CONFIG_HID8K_SIM_HOST_XFERS

/* One capture record: arrival time, length, then the report (zero padded), 80 bytes. */
struct capture_rec {
	uint64_t arrival_ns;
	uint16_t len;
	uint16_t rsvd0;
	uint32_t rsvd1;
	uint8_t data[64];
} __packed;
BUILD_ASSERT(sizeof(struct capture_rec) == 80, "capture record layout (sim_capture.py)");

#define CAPTURE_BATCH 256

static struct {
	struct sim_hid_info info;
	struct usb_device *udev;
	struct uhc_transfer *xfer[NXFERS];
	bool polling;
	/* Stream state. */
	bool have_prev;
	uint32_t next_seq;    /* the seq the next report should have */
	bool have_done;
	uint32_t prev_done_seq;
	uint32_t prev_t_done;
	uint32_t since_restart; /* reports since the stream (re)started */
	struct sim_hid_stats st;
	/* Capture. */
	int cap_fd;
	uint32_t captured;
	unsigned int cap_n;
	struct capture_rec cap[CAPTURE_BATCH];
} hid = {
	.cap_fd = -1,
};

static void stats_clear(struct sim_hid_stats *s)
{
	memset(s, 0, sizeof(*s));
	s->ival_min = UINT32_MAX;
	s->age_min = UINT32_MAX;
	s->gap_min_us = INT64_MAX;
}

static void capture_write(void)
{
	if (hid.cap_fd >= 0 && hid.cap_n > 0U) {
		const long want = (long)(hid.cap_n * sizeof(struct capture_rec));

		if (nsi_host_write(hid.cap_fd, hid.cap, (unsigned long)want) != want) {
			sim_anomaly("capture write failed");
		}
	}
	hid.cap_n = 0U;
}

static void capture(const uint8_t *data, const uint16_t len, const int64_t now_us)
{
	struct capture_rec *r;

	if (hid.cap_fd < 0) {
		return;
	}

	r = &hid.cap[hid.cap_n++];
	memset(r, 0, sizeof(*r));
	r->arrival_ns = (uint64_t)now_us * 1000U;
	r->len = MIN(len, sizeof(r->data));
	memcpy(r->data, data, r->len);
	hid.captured++;
	if (hid.cap_n == CAPTURE_BATCH) {
		capture_write();
	}
}

/* One report off the bus. */
static void check_report(const uint8_t *const d, const uint16_t len, const int64_t now_us)
{
	struct sim_hid_stats *const s = &hid.st;
	const uint32_t now_cyc = (uint32_t)now_us; /* 1 MHz: cycles == us */
	uint32_t seq;

	capture(d, len, now_us);
	s->transfers++;

	if (s->last_arrival_us != 0) {
		const int64_t gap = now_us - s->last_arrival_us;

		s->gap_n++;
		s->gap_min_us = MIN(s->gap_min_us, gap);
		s->gap_max_us = MAX(s->gap_max_us, gap);
	}
	s->last_arrival_us = now_us;

	if (len == HID8K_KBD_SIZE && d[0] == HID8K_REPORT_ID_KBD) {
		const bool f24 = (d[2U + HID8K_KEY_F24 / 8U] & BIT(HID8K_KEY_F24 % 8U)) != 0U;
		bool others = d[1] != 0U;

		for (unsigned int i = 2; i < HID8K_KBD_SIZE; i++) {
			const uint8_t mask = (i == 2U + HID8K_KEY_F24 / 8U) ?
					     (uint8_t)~BIT(HID8K_KEY_F24 % 8U) : 0xFFU;

			others |= (d[i] & mask) != 0U;
		}
		if (others) {
			sim_anomaly("keyboard report with keys other than F24");
			s->bad++;
		}
		s->kbd++;
		if (f24) {
			s->kbd_f24_down++;
		} else {
			s->kbd_f24_up++;
		}
		/* A keyboard report takes one seq; it carries none. */
		if (hid.have_prev) {
			hid.next_seq++;
		}
		hid.since_restart++;
		return;
	}

	if (len != HID8K_STATS_SIZE || d[HID8K_OFF_ID] != HID8K_REPORT_ID_STATS) {
		sim_anomaly("unexpected report: ID %u, %u bytes", d[0], len);
		s->bad++;
		return;
	}

	if (d[HID8K_OFF_FORMAT] != HID8K_FORMAT || d[HID8K_OFF_DEPTH] != DEPTH ||
	    sys_get_le32(&d[HID8K_OFF_CPU_HZ]) != CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC ||
	    (d[HID8K_OFF_FLAGS] & HID8K_FLAG_FN_VALID) != 0U ||
	    ((d[HID8K_OFF_FLAGS] & HID8K_FLAG_HIGH_SPEED) != 0U) !=
		    (hid.udev != NULL && hid.udev->speed == USB_SPEED_SPEED_HS)) {
		sim_anomaly("stats report fields: format %u depth %u cpu_hz %u flags 0x%02x",
			    d[HID8K_OFF_FORMAT], d[HID8K_OFF_DEPTH],
			    sys_get_le32(&d[HID8K_OFF_CPU_HZ]), d[HID8K_OFF_FLAGS]);
		s->bad++;
	}

	seq = sys_get_le32(&d[HID8K_OFF_SEQ]);
	if (s->stats == 0U) {
		s->first_seq = seq;
		s->first_done_seq = sys_get_le32(&d[HID8K_OFF_DONE_SEQ]);
	}
	s->stats++;
	s->last_seq = seq;

	if (hid.have_prev && seq != hid.next_seq) {
		sim_anomaly("seq %u after %u (expected %u)", seq, hid.next_seq - 1U, hid.next_seq);
		s->seq_breaks++;
	}
	hid.have_prev = true;
	hid.next_seq = seq + 1U;
	hid.since_restart++;

	/* Pacing: steady state starts once the priming reports are through. */
	{
		const uint32_t done_seq = sys_get_le32(&d[HID8K_OFF_DONE_SEQ]);
		const uint32_t t_done = sys_get_le32(&d[HID8K_OFF_T_DONE]);
		const uint32_t t_submit = sys_get_le32(&d[HID8K_OFF_T_SUBMIT]);
		const uint32_t age = now_cyc - t_submit;

		/*
		 * In steady state a report is built when the one DEPTH before it completes. Right
		 * after the queue is primed (a new configuration) or refilled from empty (the refill
		 * kick), the first reports are built back to back and name an older completion: a
		 * shorter lag, counted, not an anomaly. 0 or more than DEPTH never happens.
		 */
		if (hid.since_restart > DEPTH) {
			const uint32_t lag = seq - done_seq;

			if (lag > 0U && lag < DEPTH) {
				s->lag_short++;
			} else if (lag != DEPTH) {
				s->lag_bad++;
				sim_anomaly("seq %u names completion %u (lag %u, depth %u)", seq,
					    done_seq, lag, DEPTH);
			}
		}

		if (hid.have_done && done_seq == hid.prev_done_seq + 1U) {
			const uint32_t ival = t_done - hid.prev_t_done;

			s->ival_n++;
			s->ival_sum += ival;
			s->ival_min = MIN(s->ival_min, ival);
			s->ival_max = MAX(s->ival_max, ival);
		}
		hid.have_done = true;
		hid.prev_done_seq = done_seq;
		hid.prev_t_done = t_done;

		s->age_min = MIN(s->age_min, age);
		s->age_max = MAX(s->age_max, age);
	}

	s->refused = sys_get_le32(&d[HID8K_OFF_REFUSED]);
	s->busy = sys_get_le32(&d[HID8K_OFF_BUSY]);
	s->late = sys_get_le32(&d[HID8K_OFF_LATE]);
	s->kbd_count = sys_get_le32(&d[HID8K_OFF_KBD_COUNT]);
	s->uptime_ms = sys_get_le32(&d[HID8K_OFF_UPTIME_MS]);
	s->cdc_bytes = sys_get_le32(&d[HID8K_OFF_CDC_BYTES]);
	s->cdc_dropped = sys_get_le32(&d[HID8K_OFF_CDC_DROPPED]);
	s->flags = d[HID8K_OFF_FLAGS];
}

static int hid_in_cb(struct usb_device *const udev, struct uhc_transfer *const xfer);

/* Queue one interrupt IN transfer in slot i. */
static int submit(const unsigned int i)
{
	struct uhc_transfer *xfer;
	struct net_buf *buf;
	int ret;

	if (hid.udev == NULL || hid.xfer[i] != NULL) {
		return -EINVAL;
	}

	xfer = usbh_xfer_alloc(hid.udev, hid.info.ep, hid_in_cb, (void *)(uintptr_t)i);
	if (xfer == NULL) {
		sim_anomaly("HID: no transfer");
		return -ENOMEM;
	}

	buf = usbh_xfer_buf_alloc(hid.udev, hid.info.ep_mps);
	if (buf == NULL) {
		(void)uhc_xfer_unref(xfer);
		sim_anomaly("HID: no buffer");
		return -ENOMEM;
	}

	ret = usbh_xfer_buf_add(hid.udev, xfer, buf);
	if (ret == 0) {
		ret = usbh_xfer_enqueue(hid.udev, xfer);
	}
	if (ret != 0) {
		net_buf_unref(buf);
		(void)uhc_xfer_unref(xfer);
		sim_anomaly("HID: enqueue failed %d", ret);
		return ret;
	}

	hid.xfer[i] = xfer;

	return 0;
}

static int hid_in_cb(struct usb_device *const udev, struct uhc_transfer *const xfer)
{
	const unsigned int i = (unsigned int)(uintptr_t)xfer->priv;
	struct net_buf *buf = xfer->buf;
	const int err = xfer->err;
	const int64_t now = sim_now_us();

	ARG_UNUSED(udev);

	if (i < NXFERS && hid.xfer[i] == xfer) {
		hid.xfer[i] = NULL;
		if (err == 0 && i < ARRAY_SIZE(hid.st.per_slot)) {
			hid.st.per_slot[i]++;
		}
	}

	if (err == -ECONNRESET) {
		hid.st.cancelled++;
	} else if (err != 0) {
		hid.st.xfer_err++;
		sim_anomaly("HID transfer error %d", err);
	} else if (buf == NULL || buf->len == 0U) {
		hid.st.zero_len++;
	} else {
		check_report(buf->data, buf->len, now);
	}

	if (buf != NULL) {
		net_buf_unref(buf);
	}
	(void)uhc_xfer_unref(xfer);

	if (hid.polling && hid.udev != NULL && err != -ECONNRESET && i < NXFERS) {
		(void)submit(i);
	}

	return 0;
}

static int hid_class_init(struct usbh_class_data *const c_data)
{
	ARG_UNUSED(c_data);

	stats_clear(&hid.st);

	return 0;
}

static int hid_class_probe(struct usbh_class_data *const c_data, struct usb_device *const udev,
			   const uint8_t iface)
{
	const struct usb_cfg_descriptor *const cfg = udev->cfg_desc;
	const struct usb_if_descriptor *if_d;
	const uint8_t *p;
	const uint8_t *end;
	struct sim_hid_info info = {0};

	ARG_UNUSED(c_data);

	if_d = usbh_desc_get_iface(udev, iface);
	if (if_d == NULL || if_d->bInterfaceClass != USB_BCC_HID) {
		return -ENOTSUP;
	}

	info.iface = iface;
	info.if_class = if_d->bInterfaceClass;
	info.if_sub = if_d->bInterfaceSubClass;
	info.if_proto = if_d->bInterfaceProtocol;
	info.if_num_ep = if_d->bNumEndpoints;

	/* The HID class descriptor and the endpoints follow the interface descriptor. */
	p = (const uint8_t *)if_d + if_d->bLength;
	end = (const uint8_t *)cfg + cfg->wTotalLength;
	while (p + 2 <= end && p[0] >= 2U && p[1] != USB_DESC_INTERFACE &&
	       p[1] != USB_DESC_INTERFACE_ASSOC) {
		if (p[1] == USB_DESC_HID && p[0] >= 9U) {
			info.bcd_hid = sys_get_le16(&p[2]);
			info.rdesc_type = p[6];
			info.rdesc_len = sys_get_le16(&p[7]);
		} else if (p[1] == USB_DESC_ENDPOINT && p[0] >= 7U && USB_EP_DIR_IS_IN(p[2])) {
			const struct usb_ep_descriptor *const ep = (const void *)p;

			info.ep = ep->bEndpointAddress;
			info.ep_attr = ep->bmAttributes;
			/* usbh already converted it to CPU order in place (usbh_device.c). */
			info.ep_mps = ep->wMaxPacketSize;
			info.ep_interval = ep->bInterval;
		}
		p += p[0];
	}

	if (info.ep == 0U) {
		LOG_ERR("HID interface %u has no IN endpoint", iface);
		return -ENOTSUP;
	}

	info.bound = true;
	info.binds = hid.info.binds + 1U;
	info.removals = hid.info.removals;
	hid.info = info;
	hid.udev = udev;

	sim_print("  host: HID interface %u bound: ep 0x%02x, wMaxPacketSize %u, bInterval %u\n",
		  iface, info.ep, info.ep_mps, info.ep_interval);

	return 0;
}

static int hid_class_removed(struct usbh_class_data *const c_data)
{
	ARG_UNUSED(c_data);

	for (unsigned int i = 0; i < NXFERS; i++) {
		if (hid.xfer[i] != NULL && hid.udev != NULL) {
			(void)usbh_xfer_dequeue(hid.udev, hid.xfer[i]);
		}
	}

	hid.udev = NULL;
	hid.info.bound = false;
	hid.info.removals++;
	sim_print("  host: HID class removed\n");

	return 0;
}

static struct usbh_class_api hid_class_api = {
	.init = hid_class_init,
	.probe = hid_class_probe,
	.removed = hid_class_removed,
};

static const struct usbh_class_filter hid_filters[] = {
	{
		.class = USB_BCC_HID,
		.sub = 0,
		.proto = 0,
		.flags = USBH_CLASS_MATCH_CODE_TRIPLE,
	},
	{0},
};

USBH_DEFINE_CLASS(sim_hid8k_hid, &hid_class_api, NULL, hid_filters);

bool sim_hid_bound(void)
{
	return hid.info.bound;
}

const struct sim_hid_info *sim_hid_info(void)
{
	return &hid.info;
}

struct usb_device *sim_hid_udev(void)
{
	return hid.udev;
}

int sim_hid_poll(const bool on)
{
	int ret = 0;

	hid.polling = on;
	if (on) {
		for (unsigned int i = 0; i < NXFERS; i++) {
			if (hid.xfer[i] == NULL) {
				ret = submit(i);
				if (ret != 0) {
					break;
				}
			}
		}
	}

	return ret;
}

bool sim_hid_polling(void)
{
	return hid.polling;
}

void sim_hid_stats(struct sim_hid_stats *const out, const bool clear)
{
	*out = hid.st;
	if (clear) {
		const int64_t last = hid.st.last_arrival_us;

		stats_clear(&hid.st);
		hid.st.last_arrival_us = last;
	}
}

void sim_hid_stream_restart(void)
{
	hid.have_prev = false;
	hid.have_done = false;
	hid.since_restart = 0U;
	hid.st.last_arrival_us = 0;
}

void sim_hid_capture(const int fd)
{
	capture_write();
	hid.cap_fd = fd;
}

uint32_t sim_hid_captured(void)
{
	return hid.captured;
}

void sim_hid_capture_flush(void)
{
	capture_write();
}
