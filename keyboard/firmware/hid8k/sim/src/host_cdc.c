/*
 * hid8k-sim: a minimal CDC ACM host class driver for Zephyr's USB host stack (v4.5.0 has none).
 * It binds to the CDC ACM function (its Interface Association), keeps one bulk IN transfer
 * queued on the data interface, splits what arrives into lines, and sends command lines on the
 * bulk OUT endpoint. The firmware's numbered filler lines (heavy mode, "~fill %08x ....") are
 * checked for length and numbering and counted, not kept; other lines go into a ring the test
 * searches, with the byte count of the stream at the end of each line.
 *
 * Every line is checked to be a whole firmware line: the console drops whole lines when its ring
 * is full, never part of one (cdc_console_write()), so a filler line of the wrong length, a line
 * with "~fill" or a second "hid8k" inside it, a line that does not start with "hid8k " or
 * "~fill ", or a stats line that does not end in its "pend=" field (and an optional note) means
 * a cut line. The first line after a reconnect is not judged: the bytes the device had queued
 * at the disconnect are lost with the configuration, so it may start in the middle.
 *
 * The completion callbacks run in the host stack's cooperative "usbh" thread.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>
#include <zephyr/usb/class/usb_cdc.h>
#include <zephyr/usb/usb_ch9.h>
#include <zephyr/usb/usbh.h>

#include <nsi_host_trampolines.h>

#include <usbh_class.h>
#include <usbh_class_api.h>
#include <usbh_desc.h>
#include <usbh_device.h>

#include "sim.h"

LOG_MODULE_REGISTER(sim_cdc, LOG_LEVEL_INF);

/* The firmware's filler lines: 64 bytes with CR LF (main.c, FILL_LINE_LEN). */
#define FILL_LEN   62U
#define LINE_MAX   1100U
#define RING_LINES 128U
#define RX_SIZE    2048U

static struct {
	struct sim_cdc_info info;
	struct usb_device *udev;
	struct uhc_transfer *rx_xfer;
	bool reading;
	char cur[LINE_MAX + 1U];
	size_t cur_len;
	bool cur_overflow;
	uint32_t line_no;
	bool have_fill;
	uint32_t next_fill;
	struct {
		uint32_t no;
		uint32_t bytes_end;
		char text[LINE_MAX + 1U];
	} ring[RING_LINES];
	uint32_t pos;       /* bytes of the stream so far */
	bool resync;        /* the next line follows a reconnect: not judged */
	uint32_t ring_head; /* next slot */
	struct sim_cdc_stats st;
	int log_fd;
} cdc = {
	.log_fd = -1,
};

static void keep_line(const char *const text)
{
	const uint32_t slot = cdc.ring_head % RING_LINES;

	cdc.ring[slot].no = cdc.line_no;
	cdc.ring[slot].bytes_end = cdc.pos;
	strncpy(cdc.ring[slot].text, text, LINE_MAX);
	cdc.ring[slot].text[LINE_MAX] = '\0';
	cdc.ring_head++;
}

/* A stats line ends with "pend=<n>" and at most one of format_stats()'s notes (main.c). */
static bool stats_line_whole(const char *const s)
{
	static const char *const notes[] = {"", " CYCCNT-MISMATCH", " NO-COMPLETIONS",
					    " not-streaming"};
	const char *p = strstr(s, " pend=");
	const char *q;

	if (p == NULL) {
		return false;
	}
	while ((q = strstr(p + 1, " pend=")) != NULL) {
		p = q;
	}
	p += 6;
	if (*p < '0' || *p > '9') {
		return false;
	}
	while (*p >= '0' && *p <= '9') {
		p++;
	}
	for (size_t i = 0; i < ARRAY_SIZE(notes); i++) {
		if (strcmp(p, notes[i]) == 0) {
			return true;
		}
	}

	return false;
}

static void end_line(void)
{
	char *const s = cdc.cur;
	size_t n = cdc.cur_len;
	const bool judge = !cdc.resync;

	if (n > 0U && s[n - 1U] == '\r') {
		n--;
	}
	s[n] = '\0';

	cdc.st.lines++;
	cdc.resync = false;

	if (strncmp(s, "~fill ", 6) == 0) {
		char *endp;
		const unsigned long no = strtoul(&s[6], &endp, 16);
		bool ok = (n == FILL_LEN) && (endp == &s[14]) && (*endp == ' ');

		for (size_t i = 15U; ok && i < n; i++) {
			ok = (s[i] == '.');
		}
		if (!ok && judge) {
			cdc.st.fill_bad++;
			sim_anomaly("bad filler line (%zu chars): %.40s", n, s);
		}
		if (cdc.have_fill && (uint32_t)no != cdc.next_fill) {
			/* Counted, and judged by the test (the console drops whole lines by design). */
			cdc.st.fill_breaks++;
			if ((uint32_t)no > cdc.next_fill) {
				cdc.st.fill_missing += (uint32_t)no - cdc.next_fill;
			}
			if (cdc.st.fill_breaks <= 8U) {
				sim_print("  note: CDC filler line %08lx after %08x\n", no,
					  cdc.next_fill - 1U);
			}
		}
		cdc.have_fill = true;
		cdc.next_fill = (uint32_t)no + 1U;
		cdc.st.fill_lines++;
	} else {
		if (strncmp(s, "hid8k t=", 8) == 0) {
			cdc.st.stats_lines++;
		}
		if (cdc.cur_overflow) {
			sim_anomaly("CDC line longer than %u bytes", LINE_MAX);
		}
		if (judge && (strstr(s, "~fill") != NULL || strncmp(s, "hid8k ", 6) != 0 ||
			      strstr(&s[6], "hid8k") != NULL ||
			      (strncmp(s, "hid8k t=", 8) == 0 && !stats_line_whole(s)))) {
			cdc.st.line_bad++;
			sim_anomaly("CDC line is not a whole firmware line (%zu chars): %.60s", n,
				    s);
		}
		keep_line(s);
	}

	cdc.line_no++;
	cdc.cur_len = 0U;
	cdc.cur_overflow = false;
}

static void rx_bytes(const uint8_t *const data, const size_t len)
{
	if (cdc.log_fd >= 0 && nsi_host_write(cdc.log_fd, data, len) != (long)len) {
		sim_anomaly("CDC log write failed");
	}

	for (size_t i = 0; i < len; i++) {
		cdc.pos++;
		if (data[i] == '\n') {
			end_line();
		} else if (cdc.cur_len < LINE_MAX) {
			cdc.cur[cdc.cur_len++] = (char)data[i];
		} else {
			cdc.cur_overflow = true;
		}
	}
}

static int rx_cb(struct usb_device *const udev, struct uhc_transfer *const xfer);

static int rx_submit(void)
{
	struct uhc_transfer *xfer;
	struct net_buf *buf;
	int ret;

	if (cdc.udev == NULL || cdc.rx_xfer != NULL) {
		return -EINVAL;
	}

	xfer = usbh_xfer_alloc(cdc.udev, cdc.info.ep_in, rx_cb, NULL);
	if (xfer == NULL) {
		sim_anomaly("CDC: no transfer");
		return -ENOMEM;
	}

	buf = usbh_xfer_buf_alloc(cdc.udev, RX_SIZE);
	if (buf == NULL) {
		(void)uhc_xfer_unref(xfer);
		sim_anomaly("CDC: no buffer");
		return -ENOMEM;
	}

	ret = usbh_xfer_buf_add(cdc.udev, xfer, buf);
	if (ret == 0) {
		ret = usbh_xfer_enqueue(cdc.udev, xfer);
	}
	if (ret != 0) {
		net_buf_unref(buf);
		(void)uhc_xfer_unref(xfer);
		return ret;
	}

	cdc.rx_xfer = xfer;

	return 0;
}

static int rx_cb(struct usb_device *const udev, struct uhc_transfer *const xfer)
{
	struct net_buf *buf = xfer->buf;
	const int err = xfer->err;

	ARG_UNUSED(udev);

	if (cdc.rx_xfer == xfer) {
		cdc.rx_xfer = NULL;
	}

	if (err == 0 && buf != NULL) {
		cdc.st.rx_transfers++;
		if (buf->len == 0U) {
			cdc.st.zlp++;
		} else {
			cdc.st.rx_bytes += buf->len;
			rx_bytes(buf->data, buf->len);
		}
	} else if (err != -ECONNRESET) {
		cdc.st.xfer_err++;
		sim_anomaly("CDC IN transfer error %d", err);
	}

	if (buf != NULL) {
		net_buf_unref(buf);
	}
	(void)uhc_xfer_unref(xfer);

	if (cdc.reading && cdc.udev != NULL && err != -ECONNRESET) {
		(void)rx_submit();
	}

	return 0;
}

static int tx_cb(struct usb_device *const udev, struct uhc_transfer *const xfer)
{
	ARG_UNUSED(udev);

	if (xfer->err != 0) {
		cdc.st.xfer_err++;
		sim_anomaly("CDC OUT transfer error %d", xfer->err);
	}

	if (xfer->buf != NULL) {
		net_buf_unref(xfer->buf);
	}
	(void)uhc_xfer_unref(xfer);

	return 0;
}

static int cdc_class_init(struct usbh_class_data *const c_data)
{
	ARG_UNUSED(c_data);

	return 0;
}

static int cdc_class_probe(struct usbh_class_data *const c_data, struct usb_device *const udev,
			   const uint8_t iface)
{
	const struct usb_cfg_descriptor *const cfg = udev->cfg_desc;
	const struct usb_association_descriptor *iad;
	const uint8_t *p;
	const uint8_t *end;
	struct sim_cdc_info info = {0};
	int cur_if = -1;

	ARG_UNUSED(c_data);

	iad = usbh_desc_get_iad(udev, iface);
	if (iad == NULL || iad->bFunctionClass != USB_BCC_CDC_CONTROL || iad->bInterfaceCount != 2U) {
		return -ENOTSUP;
	}

	info.iad_class = iad->bFunctionClass;
	info.iad_sub = iad->bFunctionSubClass;
	info.iad_proto = iad->bFunctionProtocol;
	info.comm_iface = iad->bFirstInterface;

	/* Walk the function's two interfaces and their endpoints. */
	p = (const uint8_t *)iad + iad->bLength;
	end = (const uint8_t *)cfg + cfg->wTotalLength;
	while (p + 2 <= end && p[0] >= 2U && p[1] != USB_DESC_INTERFACE_ASSOC) {
		if (p[1] == USB_DESC_INTERFACE) {
			const struct usb_if_descriptor *const if_d = (const void *)p;

			if (if_d->bInterfaceNumber != iad->bFirstInterface &&
			    if_d->bInterfaceNumber != iad->bFirstInterface + 1U) {
				break;
			}
			cur_if = if_d->bInterfaceNumber;
			if (if_d->bInterfaceClass == USB_BCC_CDC_DATA) {
				info.data_iface = if_d->bInterfaceNumber;
			}
		} else if (p[1] == USB_DESC_ENDPOINT && cur_if >= 0) {
			const struct usb_ep_descriptor *const ep = (const void *)p;
			const uint8_t type = ep->bmAttributes & USB_EP_TRANSFER_TYPE_MASK;

			if (type == USB_EP_TYPE_INTERRUPT && USB_EP_DIR_IS_IN(ep->bEndpointAddress)) {
				info.ep_notify = ep->bEndpointAddress;
				info.mps_notify = ep->wMaxPacketSize;
				info.notify_interval = ep->bInterval;
			} else if (type == USB_EP_TYPE_BULK &&
				   USB_EP_DIR_IS_IN(ep->bEndpointAddress)) {
				info.ep_in = ep->bEndpointAddress;
				info.mps_in = ep->wMaxPacketSize;
			} else if (type == USB_EP_TYPE_BULK) {
				info.ep_out = ep->bEndpointAddress;
				info.mps_out = ep->wMaxPacketSize;
			}
		}
		p += p[0];
	}

	if (info.ep_in == 0U || info.ep_out == 0U) {
		LOG_ERR("CDC function at interface %u has no bulk endpoints", iface);
		return -ENOTSUP;
	}

	info.bound = true;
	info.binds = cdc.info.binds + 1U;
	info.removals = cdc.info.removals;
	cdc.info = info;
	cdc.udev = udev;

	sim_print("  host: CDC ACM interfaces %u+%u bound: bulk IN 0x%02x (%u), OUT 0x%02x (%u)\n",
		info.comm_iface, info.data_iface, info.ep_in, info.mps_in, info.ep_out,
		info.mps_out);

	return 0;
}

static int cdc_class_removed(struct usbh_class_data *const c_data)
{
	ARG_UNUSED(c_data);

	if (cdc.rx_xfer != NULL && cdc.udev != NULL) {
		(void)usbh_xfer_dequeue(cdc.udev, cdc.rx_xfer);
	}

	cdc.udev = NULL;
	cdc.info.bound = false;
	cdc.info.removals++;
	/* A line cut by the disconnect is not a line, and the next one may start in the middle. */
	cdc.cur_len = 0U;
	cdc.cur_overflow = false;
	cdc.resync = true;
	sim_print("  host: CDC ACM class removed\n");

	return 0;
}

static struct usbh_class_api cdc_class_api = {
	.init = cdc_class_init,
	.probe = cdc_class_probe,
	.removed = cdc_class_removed,
};

static const struct usbh_class_filter cdc_filters[] = {
	{
		.class = USB_BCC_CDC_CONTROL,
		.sub = ACM_SUBCLASS,
		.proto = 0,
		.flags = USBH_CLASS_MATCH_CODE_TRIPLE,
	},
	{0},
};

USBH_DEFINE_CLASS(sim_hid8k_cdc, &cdc_class_api, NULL, cdc_filters);

bool sim_cdc_bound(void)
{
	return cdc.info.bound;
}

const struct sim_cdc_info *sim_cdc_info(void)
{
	return &cdc.info;
}

int sim_cdc_start(void)
{
	cdc.reading = true;

	return cdc.rx_xfer == NULL ? rx_submit() : 0;
}

void sim_cdc_stop(void)
{
	cdc.reading = false;
}

int sim_cdc_send(const char *const line)
{
	const size_t len = strlen(line);
	struct uhc_transfer *xfer;
	struct net_buf *buf;
	int ret;

	if (cdc.udev == NULL) {
		return -ENODEV;
	}

	xfer = usbh_xfer_alloc(cdc.udev, cdc.info.ep_out, tx_cb, NULL);
	if (xfer == NULL) {
		return -ENOMEM;
	}

	buf = usbh_xfer_buf_alloc(cdc.udev, len + 2U);
	if (buf == NULL) {
		(void)uhc_xfer_unref(xfer);
		return -ENOMEM;
	}

	net_buf_add_mem(buf, line, len);
	net_buf_add_mem(buf, "\r\n", 2U);

	ret = usbh_xfer_buf_add(cdc.udev, xfer, buf);
	if (ret == 0) {
		ret = usbh_xfer_enqueue(cdc.udev, xfer);
	}
	if (ret != 0) {
		net_buf_unref(buf);
		(void)uhc_xfer_unref(xfer);
		return ret;
	}

	cdc.st.tx_bytes += len + 2U;

	return 0;
}

void sim_cdc_stats(struct sim_cdc_stats *const out)
{
	*out = cdc.st;
}

uint32_t sim_cdc_line_count(void)
{
	return cdc.line_no;
}

bool sim_cdc_find(uint32_t *const from, const char *const needle, char *const out,
		  const size_t out_len)
{
	return sim_cdc_find_at(from, needle, out, out_len, NULL);
}

bool sim_cdc_find_at(uint32_t *const from, const char *const needle, char *const out,
		     const size_t out_len, uint32_t *const bytes_end)
{
	const uint32_t n = MIN(cdc.ring_head, RING_LINES);

	/* Oldest first. */
	for (uint32_t k = 0; k < n; k++) {
		const uint32_t slot = (cdc.ring_head - n + k) % RING_LINES;

		if (cdc.ring[slot].no < *from || strstr(cdc.ring[slot].text, needle) == NULL) {
			continue;
		}
		if (out != NULL && out_len > 0U) {
			strncpy(out, cdc.ring[slot].text, out_len - 1U);
			out[out_len - 1U] = '\0';
		}
		*from = cdc.ring[slot].no + 1U;
		if (bytes_end != NULL) {
			*bytes_end = cdc.ring[slot].bytes_end;
		}
		return true;
	}

	return false;
}

void sim_cdc_log(const int fd)
{
	cdc.log_fd = fd;
}
