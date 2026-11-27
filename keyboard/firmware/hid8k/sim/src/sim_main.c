/*
 * hid8k-sim: the test. hid8k's own main() runs the firmware unchanged (USB device on the virtual
 * device controller); this file brings up Zephyr's USB host stack on the virtual host controller
 * before main() runs, and a cooperative test thread then acts as the host and as the person at
 * the bench: it checks the enumeration and the descriptors, reads the report stream, talks to the
 * CDC console, presses the button, and forces the paths a bench cannot easily force (the host
 * stops reading the CDC console, the host stops polling, suspend and resume, completions while
 * the device thinks the bus is suspended, disconnect and reconnect both ways). Every result is
 * printed as "ok", "FAIL" or "KNOWN" (a recorded firmware issue, bounded by a check); the process
 * exits non-zero if any check failed or any anomaly was seen. Built with fs.overlay, the device is
 * full speed and the same steps check what a full-speed bus does to the stream.
 *
 * What this proves and what it cannot: see README.md, "USB simulation". Time here is simulated
 * time: code takes none, so nothing about the STM32's timing, its UDC driver or its PHY is
 * tested.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio/gpio_emul.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>
#include <zephyr/usb/class/hid.h>
#include <zephyr/usb/usb_ch9.h>
#include <zephyr/usb/usbd.h>
#include <zephyr/usb/usbh.h>

#include <cmdline.h>
#include <nsi_host_trampolines.h>
#include <nsi_tracing.h>
#include <posix_board_if.h>
#include <posix_native_task.h>

#include <uhc_common.h>
#include <usbh_ch9.h>
#include <usbh_device.h>

#include "hid8k_report.h"
#include "sim.h"
#include "usb_device.h"

#define DEPTH            CONFIG_HID8K_QUEUE_DEPTH
/*
 * The device controller's speed: high speed unless sim/fs.overlay sets maximum-speed =
 * "full-speed" (the enum's index 1, dts/bindings/usb/usb-controller.yaml), which is how a
 * full-speed-only port or hub looks to the firmware. A full-speed bus has 1 ms frames whichever
 * host controller copy is built; a high-speed one has 125 us microframes only with the
 * simulation's copy (hs_fix.conf).
 */
#define SIM_FS           (DT_ENUM_IDX(DT_NODELABEL(zephyr_udc0), maximum_speed) < 2)
#define PERIOD_US        ((!SIM_FS && IS_ENABLED(CONFIG_HID8K_SIM_UHC_HS_FIX)) ? 125U : 1000U)
#define SPEED_NAME       (SIM_FS ? "full" : "high")
#define BUTTON_GPIO_PIN  1

/* main.c's stats thread tick when not in heavy mode, and its filler line length. */
#define FW_IDLE_TICK_MS  MIN(CONFIG_HID8K_LOG_PERIOD_MS, 100)
#define FW_FILL_LINE_LEN 64U

USBH_CONTROLLER_DEFINE(sim_uhs, DEVICE_DT_GET(DT_NODELABEL(zephyr_uhc0)));
struct usbh_context *const sim_uhs_ctx = &sim_uhs;

static const struct device *const gpio0 = DEVICE_DT_GET(DT_NODELABEL(gpio0));

/* ------------------------------------------------------------------ command line, host files */

static char *opt_capture;
static char *opt_cdc_log;
/* The command-line parser sets an absent 'u' option to UINT32_MAX (nsi_cmdline_common.c). */
static uint32_t opt_stream_s = UINT32_MAX;

static void sim_add_options(void)
{
	static struct args_struct_t opts[] = {
		{
			.option = "hid8k_capture",
			.name = "path",
			.type = 's',
			.dest = (void *)&opt_capture,
			.descript = "Write every HID report of the undisturbed stream (80-byte "
				    "records, sim_capture.py) to this file, which must exist and be "
				    "empty (it is written from the start, not truncated).",
		},
		{
			.option = "hid8k_cdc_log",
			.name = "path",
			.type = 's',
			.dest = (void *)&opt_cdc_log,
			.descript = "Write everything read from the CDC console to this file, "
				    "which must exist and be empty.",
		},
		{
			.option = "hid8k_stream_s",
			.name = "seconds",
			.type = 'u',
			.dest = (void *)&opt_stream_s,
			.descript = "Seconds of undisturbed stream to check (and capture).",
		},
		ARG_TABLE_ENDMARKER,
	};

	native_add_command_line_opts(opts);
}

NATIVE_TASK(sim_add_options, PRE_BOOT_1, 10);

/*
 * The file must exist: nsi_host_open() calls the host's open() with no mode argument, so it cannot
 * create one safely (and without O_TRUNC it does not shorten one).
 */
static int open_host_file(const char *const path)
{
	int fd;

	if (path == NULL || path[0] == '\0') {
		return -1;
	}

	fd = nsi_host_open(path, 1 /* the host's O_WRONLY (Linux) */);
	if (fd < 0) {
		sim_print("hid8k-sim: cannot open %s for writing (create it first)\n", path);
	}

	return fd;
}

/* ------------------------------------------------------------------ results */

static uint32_t n_checks;
static uint32_t n_failed;
static uint32_t n_anomalies;
static uint32_t n_known;

int64_t sim_now_us(void)
{
	return k_ticks_to_us_floor64(k_uptime_ticks());
}

void sim_print(const char *const fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	nsi_vprint_trace(fmt, ap);
	va_end(ap);
}

static bool check(const bool ok, const char *const fmt, ...)
{
	va_list ap;

	n_checks++;
	if (!ok) {
		n_failed++;
	}

	sim_print("  %s ", ok ? "ok  " : "FAIL");
	va_start(ap, fmt);
	nsi_vprint_trace(fmt, ap);
	va_end(ap);
	sim_print("\n");

	return ok;
}

/*
 * A behaviour of the firmware as it stands that the simulation exposes and README.md records,
 * with a proposed fix, under "What the simulation found". It does not fail the run while it is
 * there, and it prints "ok" if it ever goes away, so a fix shows up here first.
 */
static void known_issue(const bool seen, const char *const fmt, ...)
{
	va_list ap;

	if (seen) {
		n_known++;
	}

	sim_print("  %s ", seen ? "KNOWN" : "ok   ");
	va_start(ap, fmt);
	nsi_vprint_trace(fmt, ap);
	va_end(ap);
	sim_print("%s\n", seen ? " (README: What the simulation found)" : " (no longer seen)");
}

void sim_anomaly(const char *const fmt, ...)
{
	va_list ap;

	n_anomalies++;
	if (n_anomalies > 40U) {
		return;
	}

	sim_print("  ANOMALY t=%lld us: ", sim_now_us());
	va_start(ap, fmt);
	nsi_vprint_trace(fmt, ap);
	va_end(ap);
	sim_print("\n");
}

uint32_t sim_anomalies(void)
{
	return n_anomalies;
}

static void step(const char *const name)
{
	sim_print("\nhid8k-sim: [%s] t=%lld ms\n", name, sim_now_us() / 1000);
}

static void hexdump(const char *const what, const uint8_t *const d, const size_t n)
{
	sim_print("  %s (%zu bytes):", what, n);
	for (size_t i = 0; i < n; i++) {
		sim_print("%s%02x", (i % 32U == 0U) ? "\n    " : " ", d[i]);
	}
	sim_print("\n");
}

/* Sleep in short steps until cond() holds or timeout_ms passes. */
static bool wait_for(bool (*cond)(void), const int timeout_ms)
{
	for (int t = 0; t < timeout_ms; t++) {
		if (cond()) {
			return true;
		}
		k_msleep(1);
	}

	return cond();
}

static bool both_bound(void)
{
	return sim_hid_bound() && sim_cdc_bound();
}

static bool neither_bound(void)
{
	return !sim_hid_bound() && !sim_cdc_bound();
}

/* ------------------------------------------------------------------ host bring-up */

/*
 * Before main(): the host controller must be up when the device connects, or the connect event
 * is dropped (uhc_submit_event() refuses it until uhc_init(), drivers/usb/uhc/uhc_common.c).
 */
static int sim_host_init(void)
{
	int ret;

	ret = usbh_init(sim_uhs_ctx);
	if (ret == 0) {
		ret = usbh_enable(sim_uhs_ctx);
	}
	if (ret != 0) {
		sim_print("hid8k-sim: USB host init failed (%d)\n", ret);
	}

	return ret;
}

SYS_INIT(sim_host_init, APPLICATION, 0);

/* ------------------------------------------------------------------ control requests */

static int ctrl_in(const uint8_t type, const uint8_t req, const uint16_t value,
		   const uint16_t index, const uint16_t len, uint8_t *const out, size_t *const n)
{
	struct usb_device *const udev = sim_hid_udev();
	struct net_buf *buf;
	int ret;

	*n = 0U;
	if (udev == NULL) {
		return -ENODEV;
	}

	buf = usbh_xfer_buf_alloc(udev, len);
	if (buf == NULL) {
		return -ENOMEM;
	}

	ret = usbh_req_setup(udev, type, req, value, index, len, buf);
	if (ret == 0) {
		*n = MIN(buf->len, len);
		memcpy(out, buf->data, *n);
	}
	usbh_xfer_buf_free(udev, buf);

	return ret;
}

static int ctrl_out(const uint8_t type, const uint8_t req, const uint16_t value,
		    const uint16_t index, const uint8_t *const data, const uint16_t len)
{
	struct usb_device *const udev = sim_hid_udev();
	struct net_buf *buf = NULL;
	int ret;

	if (udev == NULL) {
		return -ENODEV;
	}

	if (len > 0U) {
		buf = usbh_xfer_buf_alloc(udev, len);
		if (buf == NULL) {
			return -ENOMEM;
		}
		net_buf_add_mem(buf, data, len);
	}

	ret = usbh_req_setup(udev, type, req, value, index, len, buf);
	if (buf != NULL) {
		usbh_xfer_buf_free(udev, buf);
	}

	return ret;
}

#define REQ_D2H_STD_DEV   0x80U
#define REQ_D2H_STD_IF    0x81U
#define REQ_D2H_CLASS_IF  0xA1U
#define REQ_H2D_CLASS_IF  0x21U
#define HID_GET_REPORT    0x01U
#define HID_GET_IDLE      0x02U
#define HID_SET_IDLE      0x0AU
#define CDC_SET_LINE_CODING        0x20U
#define CDC_SET_CONTROL_LINE_STATE 0x22U

/* ------------------------------------------------------------------ descriptor parsing */

struct cfg_view {
	uint16_t total;
	uint8_t num_if;
	uint8_t attributes;
	uint8_t max_power;
	bool hid;
	uint8_t hid_if, hid_class, hid_sub, hid_proto, hid_neps;
	uint16_t bcd_hid;
	uint16_t rdesc_len;
	uint8_t hid_ep_raw[7];
	uint8_t hid_ep;
	uint8_t hid_ep_attr;
	uint16_t hid_ep_mps;
	uint8_t hid_ep_interval;
	bool iad;
	uint8_t iad_first, iad_count, iad_class, iad_sub, iad_proto;
	uint8_t cdc_notify_attr, cdc_notify_interval;
	uint16_t cdc_notify_mps;
	uint16_t cdc_in_mps, cdc_out_mps;
	uint8_t cdc_in_attr, cdc_out_attr;
	unsigned int bad_lengths;
};

static void parse_cfg(const uint8_t *const d, const size_t n, struct cfg_view *const v)
{
	int cur_class = -1;

	memset(v, 0, sizeof(*v));
	if (n < 9U) {
		v->bad_lengths++;
		return;
	}

	v->total = sys_get_le16(&d[2]);
	v->num_if = d[4];
	v->attributes = d[7];
	v->max_power = d[8];

	for (size_t i = d[0]; i + 2U <= n;) {
		const uint8_t *const p = &d[i];

		if (p[0] < 2U || i + p[0] > n) {
			v->bad_lengths++;
			break;
		}

		switch (p[1]) {
		case USB_DESC_INTERFACE_ASSOC:
			v->iad = true;
			v->iad_first = p[2];
			v->iad_count = p[3];
			v->iad_class = p[4];
			v->iad_sub = p[5];
			v->iad_proto = p[6];
			break;
		case USB_DESC_INTERFACE:
			cur_class = p[5];
			if (p[5] == USB_BCC_HID) {
				v->hid = true;
				v->hid_if = p[2];
				v->hid_neps = p[4];
				v->hid_class = p[5];
				v->hid_sub = p[6];
				v->hid_proto = p[7];
			}
			break;
		case USB_DESC_HID:
			v->bcd_hid = sys_get_le16(&p[2]);
			v->rdesc_len = sys_get_le16(&p[7]);
			break;
		case USB_DESC_ENDPOINT: {
			const uint8_t type = p[3] & USB_EP_TRANSFER_TYPE_MASK;
			const uint16_t mps = sys_get_le16(&p[4]);

			if (cur_class == USB_BCC_HID && USB_EP_DIR_IS_IN(p[2])) {
				memcpy(v->hid_ep_raw, p, 7);
				v->hid_ep = p[2];
				v->hid_ep_attr = p[3];
				v->hid_ep_mps = mps;
				v->hid_ep_interval = p[6];
			} else if (cur_class == USB_BCC_CDC_CONTROL && type == USB_EP_TYPE_INTERRUPT) {
				v->cdc_notify_attr = p[3];
				v->cdc_notify_mps = mps;
				v->cdc_notify_interval = p[6];
			} else if (cur_class == USB_BCC_CDC_DATA && USB_EP_DIR_IS_IN(p[2])) {
				v->cdc_in_attr = p[3];
				v->cdc_in_mps = mps;
			} else if (cur_class == USB_BCC_CDC_DATA) {
				v->cdc_out_attr = p[3];
				v->cdc_out_mps = mps;
			}
			break;
		}
		default:
			break;
		}

		i += p[0];
	}
}

/* Input report sizes per report ID, and each ID's top-level collection usage. */
struct rdesc_view {
	unsigned int in_bits[3];
	uint32_t usage_of_id[3]; /* usage page << 16 | usage */
	bool ok;
};

static void parse_report_desc(const uint8_t *const d, const size_t n, struct rdesc_view *const v)
{
	uint32_t page = 0U;
	uint32_t size = 0U;
	uint32_t count = 0U;
	uint32_t id = 0U;
	uint32_t usage = 0U;
	uint32_t coll_usage = 0U;
	int depth = 0;

	memset(v, 0, sizeof(*v));
	v->ok = true;

	for (size_t i = 0; i < n;) {
		const uint8_t prefix = d[i];
		const unsigned int len = (prefix & 3U) == 3U ? 4U : (prefix & 3U);
		const unsigned int type = (prefix >> 2) & 3U;
		const unsigned int tag = prefix >> 4;
		uint32_t val = 0U;

		if (prefix == 0xFEU || i + 1U + len > n) {
			v->ok = false; /* long items are not used by hid8k */
			return;
		}
		for (unsigned int k = 0; k < len; k++) {
			val |= (uint32_t)d[i + 1U + k] << (8U * k);
		}

		if (type == 1U) { /* global */
			switch (tag) {
			case 0x0:
				page = val;
				break;
			case 0x7:
				size = val;
				break;
			case 0x8:
				id = val;
				if (id < ARRAY_SIZE(v->usage_of_id)) {
					v->usage_of_id[id] = coll_usage;
				} else {
					v->ok = false;
				}
				break;
			case 0x9:
				count = val;
				break;
			default:
				break;
			}
		} else if (type == 2U && tag == 0x0) { /* local: usage */
			usage = (len == 4U) ? val : ((page << 16) | val);
		} else if (type == 0U) { /* main */
			if (tag == 0x8 && id < ARRAY_SIZE(v->in_bits)) { /* Input */
				v->in_bits[id] += size * count;
			} else if (tag == 0xA) { /* Collection */
				if (depth == 0) {
					coll_usage = usage;
				}
				depth++;
			} else if (tag == 0xC) { /* End Collection */
				depth--;
			}
			usage = 0U;
		}

		i += 1U + len;
	}

	if (depth != 0) {
		v->ok = false;
	}
}

static bool string_is(const uint8_t *const d, const size_t n, const char *const want)
{
	const size_t wl = strlen(want);

	if (n < 2U || d[1] != USB_DESC_STRING || d[0] != n || n != 2U + 2U * wl) {
		return false;
	}
	for (size_t i = 0; i < wl; i++) {
		if (d[2U + 2U * i] != (uint8_t)want[i] || d[3U + 2U * i] != 0U) {
			return false;
		}
	}

	return true;
}

/* ------------------------------------------------------------------ CDC console helpers */

static uint32_t cdc_mark;

/* Wait for a line containing needle, after cdc_mark; copy it to out. */
static bool cdc_wait_line(const char *const needle, char *const out, const size_t out_len,
			  const int timeout_ms)
{
	for (int t = 0; t <= timeout_ms; t++) {
		uint32_t from = cdc_mark;

		if (sim_cdc_find(&from, needle, out, out_len)) {
			cdc_mark = from;
			return true;
		}
		k_msleep(1);
	}

	return false;
}

/* Value after "key" in a stats line, as an integer (the part before any '.'). */
static long field(const char *const line, const char *const key)
{
	const char *p = strstr(line, key);

	return p == NULL ? -1 : strtol(p + strlen(key), NULL, 10);
}

/* Completions in a stats line's window: the sum of its five histogram bands. */
static long window_completions(const char *const l)
{
	static const char *const bands[] = {"hist[<100:", " 100-150:", " 150-187.5:",
					    " 187.5-250:", " >=250:"};
	long n = 0;

	for (size_t i = 0; i < ARRAY_SIZE(bands); i++) {
		const long v = field(l, bands[i]);

		if (v < 0) {
			return -1;
		}
		n += v;
	}

	return n;
}

/* The next stats line after cdc_mark. */
static bool next_stats_line(char *const out, const size_t out_len, const int timeout_ms)
{
	return cdc_wait_line("hid8k t=", out, out_len, timeout_ms);
}

/* ------------------------------------------------------------------ the button */

static void button(const bool down)
{
	(void)gpio_emul_input_set(gpio0, BUTTON_GPIO_PIN, down ? 1 : 0);
}

/* ------------------------------------------------------------------ steps */

static char line[1200];

static void check_enumeration(void)
{
	struct usb_device *const udev = sim_hid_udev();
	const struct sim_hid_info *const hi = sim_hid_info();
	const struct sim_cdc_info *const ci = sim_cdc_info();
	static uint8_t buf[512];
	struct cfg_view hs;
	struct cfg_view fs;
	struct rdesc_view rv;
	size_t n;
	int ret;

	step("enumeration and descriptors");

	check(udev != NULL && udev->speed == (SIM_FS ? USB_SPEED_SPEED_FS : USB_SPEED_SPEED_HS),
	      "the host enumerated the device at %s speed (usb_device.speed %d)", SPEED_NAME,
	      udev != NULL ? (int)udev->speed : -1);
	if (udev == NULL) {
		return;
	}

	ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, USB_DESC_DEVICE << 8, 0, 18, buf, &n);
	check(ret == 0 && n == 18U, "GET_DESCRIPTOR(device): %d, %zu bytes", ret, n);
	hexdump("device descriptor", buf, n);
	check(sys_get_le16(&buf[8]) == CONFIG_HID8K_USB_VID &&
		      sys_get_le16(&buf[10]) == CONFIG_HID8K_USB_PID,
	      "VID:PID %04x:%04x (Kconfig %04x:%04x)", sys_get_le16(&buf[8]),
	      sys_get_le16(&buf[10]), CONFIG_HID8K_USB_VID, CONFIG_HID8K_USB_PID);
	check(sys_get_le16(&buf[2]) >= 0x0200U, "bcdUSB 0x%04x (2.0 or later)",
	      sys_get_le16(&buf[2]));
	check(buf[4] == USB_BCC_MISCELLANEOUS && buf[5] == 0x02U && buf[6] == 0x01U,
	      "device class %02x/%02x/%02x (IAD triple EF/02/01, usb_device.c)", buf[4], buf[5],
	      buf[6]);
	check(buf[7] == 64U, "bMaxPacketSize0 %u (64: the only value at high speed)", buf[7]);
	check(buf[17] == 1U, "bNumConfigurations %u", buf[17]);

	if (ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, (USB_DESC_STRING << 8) | buf[14],
		    0x0409, 255, buf + 256, &n) == 0) {
		check(string_is(buf + 256, n, CONFIG_HID8K_USB_MANUFACTURER),
		      "manufacturer string is \"%s\"", CONFIG_HID8K_USB_MANUFACTURER);
	}
	if (ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, (USB_DESC_STRING << 8) | buf[15],
		    0x0409, 255, buf + 256, &n) == 0) {
		check(string_is(buf + 256, n, CONFIG_HID8K_USB_PRODUCT), "product string is \"%s\"",
		      CONFIG_HID8K_USB_PRODUCT);
	}

	/* The configuration the host chose: the one for the bus speed. */
	ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, USB_DESC_CONFIGURATION << 8, 0,
		      sizeof(buf), buf, &n);
	check(ret == 0 && n >= 9U && n == sys_get_le16(&buf[2]),
	      "GET_DESCRIPTOR(configuration): %d, %zu bytes, wTotalLength %u", ret, n,
	      n >= 4U ? sys_get_le16(&buf[2]) : 0U);
	hexdump(SIM_FS ? "full-speed configuration descriptor" : "high-speed configuration descriptor",
		buf, n);
	parse_cfg(buf, n, &hs);
	check(hs.bad_lengths == 0U && hs.num_if == 3U, "3 interfaces (HID, CDC comm, CDC data): %u",
	      hs.num_if);
	check((hs.attributes & USB_SCD_SELF_POWERED) != 0U &&
		      hs.max_power == CONFIG_HID8K_USB_MAX_POWER,
	      "self-powered, bMaxPower %u (%u mA)", hs.max_power, 2U * hs.max_power);
	check(hs.hid && hs.hid_class == USB_BCC_HID && hs.hid_sub == 0U && hs.hid_proto == 0U &&
		      hs.hid_neps == 1U,
	      "HID interface %u: class %02x/%02x/%02x, %u endpoint (no boot protocol, no OUT)",
	      hs.hid_if, hs.hid_class, hs.hid_sub, hs.hid_proto, hs.hid_neps);
	check(hs.bcd_hid == USB_HID_VERSION && hs.rdesc_len == 56U,
	      "HID descriptor: bcdHID 0x%04x, report descriptor %u bytes", hs.bcd_hid,
	      hs.rdesc_len);
	hexdump("HID interrupt IN endpoint descriptor, this speed", hs.hid_ep_raw, 7);
	check((hs.hid_ep_attr & USB_EP_TRANSFER_TYPE_MASK) == USB_EP_TYPE_INTERRUPT,
	      "HID IN endpoint 0x%02x is interrupt (bmAttributes 0x%02x)", hs.hid_ep,
	      hs.hid_ep_attr);
	check(hs.hid_ep_mps == HID8K_STATS_SIZE, "HID IN wMaxPacketSize %u at %s speed",
	      hs.hid_ep_mps, SPEED_NAME);
	check(hs.hid_ep_interval == 1U, SIM_FS ?
	      "HID IN bInterval %u at full speed: 1 frame = 1 ms (the most full speed allows)" :
	      "HID IN bInterval %u at high speed: 2^(1-1) = 1 microframe = 125 us",
	      hs.hid_ep_interval);
	check(hi->ep == hs.hid_ep && hi->ep_mps == hs.hid_ep_mps &&
		      hi->ep_interval == hs.hid_ep_interval,
	      "the host class bound the same endpoint (0x%02x, %u, %u)", hi->ep, hi->ep_mps,
	      hi->ep_interval);
	check(hs.iad && hs.iad_class == USB_BCC_CDC_CONTROL && hs.iad_count == 2U,
	      "CDC ACM function: IAD %02x/%02x/%02x over interfaces %u-%u", hs.iad_class,
	      hs.iad_sub, hs.iad_proto, hs.iad_first, hs.iad_first + hs.iad_count - 1U);
	check(hs.cdc_in_mps == (SIM_FS ? 64U : 512U) && hs.cdc_out_mps == hs.cdc_in_mps,
	      "CDC bulk IN/OUT wMaxPacketSize %u/%u (%u at %s speed)", hs.cdc_in_mps,
	      hs.cdc_out_mps, SIM_FS ? 64U : 512U, SPEED_NAME);
	check(ci->mps_in == hs.cdc_in_mps, "the host CDC class bound bulk IN 0x%02x and OUT 0x%02x",
	      ci->ep_in, ci->ep_out);
	sim_print("  CDC notification endpoint: interrupt, wMaxPacketSize %u, bInterval %u\n",
	       hs.cdc_notify_mps, hs.cdc_notify_interval);

	/*
	 * The device qualifier and the other-speed (full-speed) configuration. A device that is
	 * not high-speed capable answers both with a request error (USB 2.0 9.6.2; usbd_ch9.c,
	 * sreq_get_dev_qualifier()): the full-speed variant checks that, and that the firmware
	 * built no high-speed configuration (usb_device.c).
	 */
	if (SIM_FS) {
		ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR,
			      USB_DESC_DEVICE_QUALIFIER << 8, 0, 10, buf, &n);
		check(ret != 0, "device qualifier: refused (%d): not high-speed capable", ret);
		ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, USB_DESC_OTHER_SPEED << 8, 0,
			      sizeof(buf), buf, &n);
		check(ret != 0, "other speed configuration: refused (%d)", ret);
		goto report_descriptor;
	}
	ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, USB_DESC_DEVICE_QUALIFIER << 8, 0,
		      10, buf, &n);
	check(ret == 0 && n == 10U && buf[1] == USB_DESC_DEVICE_QUALIFIER && buf[7] == 64U &&
		      buf[8] == 1U,
	      "device qualifier: %d, %zu bytes, bMaxPacketSize0 %u, bNumConfigurations %u", ret,
	      n, n == 10U ? buf[7] : 0U, n == 10U ? buf[8] : 0U);
	ret = ctrl_in(REQ_D2H_STD_DEV, USB_SREQ_GET_DESCRIPTOR, USB_DESC_OTHER_SPEED << 8, 0,
		      sizeof(buf), buf, &n);
	check(ret == 0 && n >= 9U && buf[1] == USB_DESC_OTHER_SPEED,
	      "GET_DESCRIPTOR(other speed configuration): %d, %zu bytes", ret, n);
	parse_cfg(buf, n, &fs);
	hexdump("HID interrupt IN endpoint descriptor, full speed (other speed)", fs.hid_ep_raw,
		7);
	check(fs.hid_ep_mps == 64U && fs.hid_ep_interval == 1U,
	      "full speed: HID IN wMaxPacketSize %u, bInterval %u (1 ms: 8 kHz needs high speed)",
	      fs.hid_ep_mps, fs.hid_ep_interval);
	check(fs.cdc_in_mps == 64U, "full speed: CDC bulk wMaxPacketSize %u", fs.cdc_in_mps);

report_descriptor:
	/* The report descriptor, and the report sizes it declares. */
	ret = ctrl_in(REQ_D2H_STD_IF, USB_SREQ_GET_DESCRIPTOR, USB_DESC_HID_REPORT << 8, hs.hid_if,
		      255, buf, &n);
	check(ret == 0 && n == hs.rdesc_len, "GET_DESCRIPTOR(report): %d, %zu bytes", ret, n);
	hexdump("report descriptor", buf, n);
	parse_report_desc(buf, n, &rv);
	check(rv.ok, "report descriptor parses (short items, balanced collections)");
	check(1U + rv.in_bits[HID8K_REPORT_ID_KBD] / 8U == HID8K_KBD_SIZE &&
		      rv.in_bits[HID8K_REPORT_ID_KBD] % 8U == 0U,
	      "report ID 1 is %u bits + ID = %u bytes (HID8K_KBD_SIZE %u)",
	      rv.in_bits[HID8K_REPORT_ID_KBD], 1U + rv.in_bits[HID8K_REPORT_ID_KBD] / 8U,
	      HID8K_KBD_SIZE);
	check(1U + rv.in_bits[HID8K_REPORT_ID_STATS] / 8U == HID8K_STATS_SIZE,
	      "report ID 2 is %u bits + ID = %u bytes (HID8K_STATS_SIZE %u)",
	      rv.in_bits[HID8K_REPORT_ID_STATS], 1U + rv.in_bits[HID8K_REPORT_ID_STATS] / 8U,
	      HID8K_STATS_SIZE);
	check(rv.usage_of_id[HID8K_REPORT_ID_KBD] == 0x00010006U,
	      "report ID 1 is in a Generic Desktop / Keyboard collection (0x%08x)",
	      rv.usage_of_id[HID8K_REPORT_ID_KBD]);
	check(rv.usage_of_id[HID8K_REPORT_ID_STATS] ==
		      ((HID8K_VENDOR_USAGE_PAGE << 16) | HID8K_VENDOR_USAGE),
	      "report ID 2 is in the vendor collection 0x%04x/0x%02x (0x%08x)",
	      HID8K_VENDOR_USAGE_PAGE, HID8K_VENDOR_USAGE, rv.usage_of_id[HID8K_REPORT_ID_STATS]);

	/* Class requests a host driver makes. */
	ret = ctrl_in(REQ_D2H_CLASS_IF, HID_GET_REPORT, (1U << 8) | HID8K_REPORT_ID_STATS,
		      hs.hid_if, HID8K_STATS_SIZE, buf, &n);
	check(ret == 0 && n == HID8K_STATS_SIZE && buf[0] == HID8K_REPORT_ID_STATS &&
		      buf[1] == HID8K_FORMAT,
	      "GET_REPORT(input, 2): %d, %zu bytes, ID %u, format %u", ret, n, n ? buf[0] : 0U,
	      n > 1U ? buf[1] : 0U);
	ret = ctrl_in(REQ_D2H_CLASS_IF, HID_GET_REPORT, (1U << 8) | HID8K_REPORT_ID_KBD,
		      hs.hid_if, 64, buf, &n);
	check(ret == 0 && n == HID8K_KBD_SIZE && buf[0] == HID8K_REPORT_ID_KBD,
	      "GET_REPORT(input, 1): %d, %zu bytes", ret, n);
	ret = ctrl_out(REQ_H2D_CLASS_IF, HID_SET_IDLE, (0x10U << 8) | HID8K_REPORT_ID_STATS,
		       hs.hid_if, NULL, 0);
	check(ret == 0, "SET_IDLE(64 ms, ID 2): %d", ret);
	ret = ctrl_in(REQ_D2H_CLASS_IF, HID_GET_IDLE, HID8K_REPORT_ID_STATS, hs.hid_if, 1, buf, &n);
	check(ret == 0 && n == 1U && buf[0] == 0x10U, "GET_IDLE(ID 2) = 0x%02x (stored only)",
	      n ? buf[0] : 0U);
	(void)ctrl_out(REQ_H2D_CLASS_IF, HID_SET_IDLE, HID8K_REPORT_ID_STATS, hs.hid_if, NULL, 0);

	/* What a terminal does when it opens the port: 115200 8N1, DTR and RTS. */
	{
		const uint8_t coding[7] = {0x00, 0xC2, 0x01, 0x00, 0, 0, 8};

		ret = ctrl_out(REQ_H2D_CLASS_IF, CDC_SET_LINE_CODING, 0, ci->comm_iface, coding, 7);
		check(ret == 0, "CDC SET_LINE_CODING: %d", ret);
		ret = ctrl_out(REQ_H2D_CLASS_IF, CDC_SET_CONTROL_LINE_STATE, 3, ci->comm_iface, NULL,
			       0);
		check(ret == 0, "CDC SET_CONTROL_LINE_STATE(DTR, RTS): %d", ret);
	}
}

/* Expected reports in a window of ms at the simulated frame rate. */
static uint32_t frames_in(const uint32_t ms)
{
	return ms * 1000U / PERIOD_US;
}

static bool within(const uint32_t v, const uint32_t want, const uint32_t tol)
{
	return v + tol >= want && v <= want + tol;
}

/* Counters that may legitimately have moved before a stretch starts (see known_issue()). */
struct baseline {
	uint32_t late, refused, busy, cdc_dropped;
};

static struct baseline baseline_now(void)
{
	struct sim_hid_stats s;
	struct baseline b;

	sim_hid_stats(&s, false);
	b.late = s.late;
	b.refused = s.refused;
	b.busy = s.busy;
	b.cdc_dropped = s.cdc_dropped;

	return b;
}

/*
 * Check one undisturbed stretch of the stream (the stats were cleared at its start). With
 * cdc_may_drop the CDC console is allowed to drop lines meanwhile (nobody reads it).
 */
static void check_stream_ex(const char *const what, const uint32_t ms, const struct baseline *b,
			    const bool heavy, const bool cdc_may_drop)
{
	struct sim_hid_stats s;
	const uint32_t want = frames_in(ms);

	sim_hid_stats(&s, false);
	check(within(s.transfers, want, 2U), "%s: %u reports in %u ms (%u frames of %u us)",
	      what, s.transfers, ms, want, PERIOD_US);
	if (CONFIG_HID8K_SIM_HOST_XFERS > 1) {
		sim_print("  %s: completed transfers per host transfer slot: %u, %u\n", what,
		       s.per_slot[0], s.per_slot[1]);
	}
	check(s.bad == 0U && s.xfer_err == 0U && s.zero_len == 0U,
	      "%s: no bad reports (%u), transfer errors (%u) or empty transfers (%u)", what, s.bad,
	      s.xfer_err, s.zero_len);
	check(s.seq_breaks == 0U && s.stats > 0U, "%s: seq %u..%u continuous (%u breaks)", what,
	      s.first_seq, s.last_seq, s.seq_breaks);
	check(s.lag_bad == 0U && s.lag_short == 0U,
	      "%s: every report names the completion %u before it (%u short, %u wrong)", what,
	      DEPTH, s.lag_short, s.lag_bad);
	check(s.ival_n > 0U && s.ival_min == PERIOD_US && s.ival_max == PERIOD_US,
	      "%s: device completion interval %u..%u us over %u (the frame, exactly)", what,
	      s.ival_min, s.ival_max, s.ival_n);
	check(s.gap_min_us == PERIOD_US && s.gap_max_us == PERIOD_US,
	      "%s: host arrival interval %lld..%lld us", what, s.gap_min_us, s.gap_max_us);
	check(s.age_min == DEPTH * PERIOD_US && s.age_max == DEPTH * PERIOD_US,
	      "%s: each report is %u..%u us old when the host takes it (depth %u x %u us)", what,
	      s.age_min, s.age_max, DEPTH, PERIOD_US);
	check(s.refused == b->refused && s.busy == b->busy,
	      "%s: refused %u -> %u, busy %u -> %u (no change)", what, b->refused, s.refused,
	      b->busy, s.busy);
	if (PERIOD_US == 125U) {
		check(s.late == b->late, "%s: late %u -> %u (no interval above 187.5 us)", what,
		      b->late, s.late);
	} else {
		check(s.late - b->late >= s.ival_n,
		      "%s: late %u -> %u: every 1 ms interval counts as late, as it should", what,
		      b->late, s.late);
	}
	check(((s.flags & HID8K_FLAG_CDC_HEAVY) != 0U) == heavy,
	      "%s: heavy-CDC flag %s in the reports", what, heavy ? "set" : "clear");
	if (!cdc_may_drop) {
		check(s.cdc_dropped == b->cdc_dropped, "%s: CDC bytes dropped %u -> %u (no change)",
		      what, b->cdc_dropped, s.cdc_dropped);
	}
}

static void check_stream(const char *const what, const uint32_t ms, const struct baseline *b,
			 const bool heavy)
{
	check_stream_ex(what, ms, b, heavy, false);
}

static void stream(const char *const what, const uint32_t ms, const bool heavy)
{
	struct sim_hid_stats s;
	struct baseline b = baseline_now();

	sim_hid_stats(&s, true);
	k_msleep(ms);
	check_stream(what, ms, &b, heavy);
}

/* Seconds in a stats line's "t=" field. */
static long line_t(const char *const l)
{
	return field(l, "hid8k t=");
}

/*
 * The first stats line stamped at or after t_min_s (lines held back by a suspend arrive late),
 * after cdc_mark.
 */
static bool stats_line_from(const long t_min_s, char *const out, const size_t out_len,
			    const int timeout_ms)
{
	const int64_t end = sim_now_us() + (int64_t)timeout_ms * 1000;

	while (sim_now_us() <= end) {
		if (next_stats_line(out, out_len, 0) && line_t(out) >= t_min_s) {
			return true;
		}
		k_msleep(1);
	}

	return false;
}

static void check_stats_line(const char *const what, const bool heavy, const uint32_t dropped)
{
	const long rate_want = (long)(1000000U / PERIOD_US);

	if (!check(next_stats_line(line, sizeof(line), 1500), "%s: a stats line arrives", what)) {
		return;
	}
	sim_print("  | %s\n", line);
	check(strstr(line, SIM_FS ? "usb=cfg fs " : "usb=cfg hs ") != NULL, "%s: usb=cfg %s", what,
	      SIM_FS ? "fs" : "hs");
	check(field(line, "rate=") >= rate_want - 1 && field(line, "rate=") <= rate_want,
	      "%s: rate=%ld/s on the device clock (%ld expected)", what, field(line, "rate="),
	      rate_want);
	check(field(line, "out=") == DEPTH, "%s: out=%ld (the queue depth)", what,
	      field(line, "out="));
	check(field(line, "refused=") == 0 && field(line, "busy=") == 0,
	      "%s: refused=0 busy=0 in the window", what);
	check(field(line, "drop=") == (long)dropped, "%s: drop=%ld (%u expected)", what,
	      field(line, "drop="), dropped);
	check((strstr(line, "cdc=heavy") != NULL) == heavy, "%s: cdc=%s", what,
	      heavy ? "heavy" : "normal");
	check(strstr(line, "NO-COMPLETIONS") == NULL && strstr(line, "MISMATCH") == NULL,
	      "%s: no NO-COMPLETIONS or CYCCNT-MISMATCH note", what);
}

/*
 * Still capturing: one press and release of the button, as at the bench's step 2. Keyboard
 * reports take a seq each but are not stats reports, so this part of the capture is what shows
 * that the host tool accounts for them through kbd_count (hid8k_analysis.py, sequence_check())
 * instead of counting them as lost reports.
 */
static void stream_with_press(const char *const what, const uint32_t ms)
{
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	const uint32_t want = frames_in(ms);

	sim_hid_stats(&s0, true);
	k_msleep(ms / 3U);
	button(true);
	k_msleep(ms / 3U);
	button(false);
	k_msleep(ms - 2U * (ms / 3U));
	sim_hid_stats(&s1, false);
	check(within(s1.transfers, want, 2U),
	      "%s: %u reports in %u ms, the keyboard reports among them", what, s1.transfers, ms);
	check(s1.kbd == 2U && s1.kbd_f24_down == 1U && s1.kbd_f24_up == 1U,
	      "%s: one F24-down and one key-up report (%u, %u)", what, s1.kbd_f24_down,
	      s1.kbd_f24_up);
	check(s1.kbd_count - s0.kbd_count == 2U, "%s: kbd_count +%u", what,
	      s1.kbd_count - s0.kbd_count);
	check(s1.seq_breaks == 0U && s1.bad == 0U && s1.xfer_err == 0U && s1.lag_short == 0U &&
		      s1.lag_bad == 0U,
	      "%s: seq continuous, every report well formed, pacing kept", what);
	check(s1.refused == s0.refused && s1.busy == s0.busy, "%s: refused and busy unchanged",
	      what);
}

static void step_stream(void)
{
	const uint32_t secs = (opt_stream_s == UINT32_MAX) ? CONFIG_HID8K_SIM_STREAM_S : opt_stream_s;
	struct baseline b = baseline_now();
	int fd;

	step("undisturbed stream, then one key press (both captured)");
	check(b.cdc_dropped == 0U && b.refused == 0U && b.busy == 0U,
	      "since boot: refused %u, busy %u, CDC bytes dropped %u", b.refused, b.busy,
	      b.cdc_dropped);
	fd = open_host_file(opt_capture);
	if (fd >= 0) {
		sim_print("  capturing to %s\n", opt_capture);
	}
	sim_hid_capture(fd);
	cdc_mark = sim_cdc_line_count();
	stream("stream", secs * 1000U, false);
	stream_with_press("stream, one key press", 1000U);
	sim_hid_capture(-1);
	if (fd >= 0) {
		sim_print("  captured %u reports\n", sim_hid_captured());
		nsi_host_close(fd);
	}
	check_stats_line("stream", false, 0U);
}

static void step_commands(void)
{
	struct sim_cdc_stats c1;

	step("CDC console commands");

	cdc_mark = sim_cdc_line_count();
	(void)sim_cdc_send("help");
	check(cdc_wait_line("hid8k commands", line, sizeof(line), 1000), "help: %s", line);
	check(cdc_wait_line("hid8k config: queue_depth=", line, sizeof(line), 1000), "help: %s",
	      line);
	(void)sim_cdc_send("hist");
	check(cdc_wait_line("hid8k hist since reset:", line, sizeof(line), 1500),
	      "hist: the cumulative histogram arrives");
	sim_print("  | %.200s\n", line);
	(void)sim_cdc_send("reset");
	check(cdc_wait_line("hid8k stats reset", line, sizeof(line), 1500), "reset: acknowledged");
	/*
	 * A reset prints a stats line at once (main.c), and then main.c also advances next_line by
	 * a period, so the regular line that was due next is skipped and the following window runs
	 * up to two periods.
	 */
	if (check(next_stats_line(line, sizeof(line), 2 * CONFIG_HID8K_LOG_PERIOD_MS + 500),
		  "after reset: the next stats line arrives")) {
		const long n = window_completions(line);
		const long per = (long)frames_in(CONFIG_HID8K_LOG_PERIOD_MS);

		check(n > 0 && n <= 2 * per + 2,
		      "after reset: its window holds %ld completions, at most two periods' (%ld)", n,
		      2 * per);
		known_issue(n > per + per / 10 + 2,
			    "reset: the regular stats line after the reset's own line was skipped: "
			    "the next window held %ld completions, %ld ms",
			    n, n * (long)PERIOD_US / 1000);
	}
	(void)sim_cdc_send("frobnicate");
	check(cdc_wait_line("hid8k unknown command", line, sizeof(line), 1500),
	      "an unknown command is answered");
	/* 40 characters: longer than any command, so ignored (an echoing terminal cannot trigger one). */
	cdc_mark = sim_cdc_line_count();
	(void)sim_cdc_send("heavyheavyheavyheavyheavyheavyheavyheavy");
	k_msleep(1200);
	{
		uint32_t from = cdc_mark;
		const bool unknown = sim_cdc_find(&from, "hid8k unknown command", NULL, 0);

		from = cdc_mark;
		check(!unknown && !sim_cdc_find(&from, "mode=heavy", NULL, 0),
		      "a 40-character line is ignored, not taken as a command");
	}
	sim_cdc_stats(&c1);
	check(c1.xfer_err == 0U, "CDC transfers without error (%u)", c1.xfer_err);
}

static uint32_t dropped_after_heavy;

static void step_heavy(void)
{
	struct sim_cdc_stats c0;
	struct sim_cdc_stats c1;
	struct sim_hid_stats s;
	const uint32_t ms = 2000U;
	uint32_t drop0;
	uint32_t want;

	step("heavy CDC traffic while streaming");
	sim_hid_stats(&s, false);
	drop0 = s.cdc_dropped;
	sim_cdc_stats(&c0);
	cdc_mark = sim_cdc_line_count();
	(void)sim_cdc_send("heavy");
	check(cdc_wait_line("hid8k mode=heavy", line, sizeof(line), 1000), "heavy: acknowledged");
	k_msleep(50);
	sim_hid_stats(&s, false);
	sim_cdc_stats(&c1);
	/*
	 * main.c resets fill_owed_x1000 when the mode changes but not last_tick, so the first heavy
	 * tick owes the whole idle tick (up to 100 ms, 10,000 bytes) at once, more than the 8192-byte
	 * ring holds: whole lines are dropped once, at every switch to heavy.
	 */
	{
		/*
		 * The most that burst can drop: one idle tick's filler, less what the ring holds.
		 * More than that is a different fault, and a FAIL, not this known issue.
		 */
		const uint32_t burst = (uint32_t)((uint64_t)CONFIG_HID8K_CDC_HEAVY_BPS *
						  FW_IDLE_TICK_MS / 1000U / FW_FILL_LINE_LEN);
		const uint32_t ring = CONFIG_HID8K_CDC_RING_SIZE / FW_FILL_LINE_LEN;
		const uint32_t bound = burst > ring ? (burst - ring) * FW_FILL_LINE_LEN : 0U;
		const uint32_t dropped = s.cdc_dropped - drop0;
		const uint32_t missing = c1.fill_missing - c0.fill_missing;

		check(dropped <= bound && missing * FW_FILL_LINE_LEN == dropped,
		      "heavy: the switch dropped %u bytes: at most the %u the start burst can (one "
		      "%u ms tick of filler beyond the %u-byte ring), and exactly the %u filler lines "
		      "missing at the host",
		      dropped, bound, FW_IDLE_TICK_MS, CONFIG_HID8K_CDC_RING_SIZE, missing);
		known_issue(dropped > 0U || c1.fill_breaks > c0.fill_breaks,
			    "heavy: the switch to heavy mode dropped %u bytes (%u filler lines "
			    "missing)", dropped, missing);
	}
	dropped_after_heavy = s.cdc_dropped;

	sim_cdc_stats(&c0);
	stream("heavy", ms, true);
	sim_cdc_stats(&c1);
	want = (uint32_t)((uint64_t)CONFIG_HID8K_CDC_HEAVY_BPS * ms / 1000U / 64U);
	check(within(c1.fill_lines - c0.fill_lines, want, want / 20U + 2U),
	      "heavy: %u filler lines in %u ms (%u at %u B/s)", c1.fill_lines - c0.fill_lines, ms,
	      want, CONFIG_HID8K_CDC_HEAVY_BPS);
	check(c1.fill_breaks == c0.fill_breaks && c1.fill_bad == 0U,
	      "heavy: filler lines numbered without a break (%u) and well formed (%u bad)",
	      c1.fill_breaks - c0.fill_breaks, c1.fill_bad);
	cdc_mark = sim_cdc_line_count();
	check_stats_line("heavy", true, dropped_after_heavy);
	(void)sim_cdc_send("normal");
	check(cdc_wait_line("hid8k mode=normal", line, sizeof(line), 1000), "normal: acknowledged");
}

/*
 * A host that stops reading the console (no terminal open, a closed port: Linux cdc-acm and
 * Windows usbser read the bulk IN endpoint only while the port is open) while heavy mode writes
 * 100 kB/s. The device's CDC buffers and then the firmware's ring fill up, and the console must
 * drop whole lines, count them, keep the HID stream untouched, and recover when reading resumes.
 * Lines of other lengths go in first, so the ring fills at a point that is not a filler-line
 * boundary: a console that wrote part of a line there is caught as a cut line.
 */
static void step_cdc_backlog(void)
{
	struct sim_cdc_stats c0;
	struct sim_cdc_stats c1;
	struct sim_hid_stats s;
	struct baseline b0;
	struct baseline b;
	const uint32_t ms = 1500U;
	uint32_t bytes_end = 0U;
	bool found = false;
	long q = -1;

	step("the host stops reading the CDC console (port closed), heavy mode, then reads again");
	b0 = baseline_now();
	sim_cdc_stats(&c0);
	sim_cdc_stop();
	k_msleep(20);
	(void)sim_cdc_send("help");
	k_msleep(150);
	(void)sim_cdc_send("heavy");
	k_msleep(150);

	b = baseline_now();
	sim_hid_stats(&s, true);
	k_msleep(ms);
	check_stream_ex("CDC not read", ms, &b, true, true);
	sim_hid_stats(&s, false);
	check(s.cdc_dropped > b.cdc_dropped,
	      "CDC not read: the console dropped %u bytes meanwhile (its ring was full)",
	      s.cdc_dropped - b.cdc_dropped);

	cdc_mark = sim_cdc_line_count();
	(void)sim_cdc_start();
	k_msleep(50);
	(void)sim_cdc_send("normal");
	check(cdc_wait_line("hid8k mode=normal", line, sizeof(line), 2000),
	      "reading again: the backlog drains and \"normal\" is acknowledged");
	k_msleep(200);
	sim_cdc_stats(&c1);
	sim_hid_stats(&s, false);
	check(c1.fill_bad == c0.fill_bad && c1.line_bad == c0.line_bad,
	      "every line that arrived is whole (%u bad filler lines, %u other cut lines): the "
	      "console drops whole lines, never part of one",
	      c1.fill_bad - c0.fill_bad, c1.line_bad - c0.line_bad);
	check(c1.fill_breaks > c0.fill_breaks &&
		      (c1.fill_missing - c0.fill_missing) * FW_FILL_LINE_LEN <=
			      s.cdc_dropped - b0.cdc_dropped,
	      "the filler numbering shows the dropped lines (%u breaks, %u lines = %u bytes), "
	      "within the %u bytes the firmware counted as dropped",
	      c1.fill_breaks - c0.fill_breaks, c1.fill_missing - c0.fill_missing,
	      (c1.fill_missing - c0.fill_missing) * FW_FILL_LINE_LEN,
	      s.cdc_dropped - b0.cdc_dropped);

	/*
	 * Exact accounting: a stats line's q= is the bytes the console queued since boot before
	 * that line (main.c formats it, then writes it), so the host's byte count at the end of the
	 * line must be q plus the line and its CR LF: nothing queued was lost on the way (the
	 * class, the bus, the backlog), and nothing arrived that was not queued.
	 */
	cdc_mark = sim_cdc_line_count();
	for (int t = 0; t < 2 * CONFIG_HID8K_LOG_PERIOD_MS + 500 && !found; t++) {
		uint32_t from = cdc_mark;

		found = sim_cdc_find_at(&from, "hid8k t=", line, sizeof(line), &bytes_end);
		if (!found) {
			k_msleep(1);
		}
	}
	if (found) {
		q = field(line, " q=");
	}
	check(found && q >= 0 && bytes_end == (uint32_t)q + (uint32_t)strlen(line) + 2U,
	      "every byte the console queued since boot reached the host, and nothing else: %u "
	      "bytes read by the end of the next stats line = q=%ld + its %zu bytes",
	      bytes_end, q, found ? strlen(line) + 2U : 0U);
	check(c1.xfer_err == c0.xfer_err, "CDC transfers without error (%u)",
	      c1.xfer_err - c0.xfer_err);
}

static void step_keyboard(void)
{
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;

	step("button: keyboard reports in the stream");
	sim_hid_stats(&s0, true);
	button(true);
	k_msleep(200);
	button(false);
	k_msleep(200);
	sim_hid_stats(&s1, false);
	check(s1.kbd_f24_down == 1U && s1.kbd_f24_up == 1U,
	      "one F24-down and one key-up report (%u, %u)", s1.kbd_f24_down, s1.kbd_f24_up);
	check(s1.kbd_count - s0.kbd_count == 2U, "kbd_count +%u", s1.kbd_count - s0.kbd_count);
	check(s1.seq_breaks == 0U && s1.bad == 0U && s1.lag_short == 0U && s1.lag_bad == 0U,
	      "seq continuous through the keyboard reports (they take a seq each), pacing kept");
}

static void step_host_stops(void)
{
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	/* Long enough that one whole 1 s stats window has no completion. */
	const uint32_t pause_ms = 2200U;
	bool no_compl = false;

	step("host stops polling (no suspend), with the button pressed meanwhile");
	(void)sim_hid_poll(false);
	k_msleep(5);
	sim_hid_stats(&s0, true);
	cdc_mark = sim_cdc_line_count();
	k_msleep(300);
	button(true); /* the IN queue is full: this report has to wait */
	k_msleep(pause_ms - 300U);
	{
		uint32_t from = cdc_mark;

		while (sim_cdc_find(&from, "hid8k t=", line, sizeof(line))) {
			if (strstr(line, "NO-COMPLETIONS") != NULL) {
				no_compl = true;
				sim_print("  | %s\n", line);
				check(field(line, "out=") == DEPTH,
				      "while not polled: out=%ld (the queue stays full)",
				      field(line, "out="));
				break;
			}
		}
	}
	check(no_compl, "while not polled: a stats line says NO-COMPLETIONS");
	sim_hid_stats(&s1, true);
	check(s1.transfers == 0U, "no reports while not polled (%u)", s1.transfers);

	(void)sim_hid_poll(true);
	k_msleep(20);
	sim_hid_stats(&s1, false);
	check(s1.seq_breaks == 0U, "polling again: seq continues without a break");
	check(s1.kbd_f24_down == 1U, "the F24 report that waited arrives (%u)", s1.kbd_f24_down);
	check(s1.age_max >= pause_ms * 1000U,
	      "the reports that waited are %u us old: stale data, as designed", s1.age_max);
	check(s1.refused == s0.refused && s1.busy == s0.busy,
	      "refused and busy unchanged (%u, %u)", s1.refused, s1.busy);
	button(false);
	k_msleep(100);

	/* A press and release both inside a stall is never reported: the firmware samples the level. */
	(void)sim_hid_poll(false);
	k_msleep(5);
	sim_hid_stats(&s0, true);
	button(true);
	k_msleep(50);
	button(false);
	k_msleep(100);
	(void)sim_hid_poll(true);
	k_msleep(100);
	sim_hid_stats(&s1, false);
	check(s1.kbd == 0U,
	      "a press shorter than a polling stall is not reported (%u keyboard reports): the "
	      "firmware sends the button's level at a completion, not its edges",
	      s1.kbd);
	check(s1.seq_breaks == 0U, "seq continuous");
}

static void step_suspend(void)
{
	const struct device *const uhc = sim_uhs_ctx->dev;
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	int ret;

	step("bus suspend and resume");
	sim_hid_stats(&s0, true);
	ret = uhc_bus_suspend(uhc);
	check(ret == 0, "host suspends the bus: %d", ret);
	k_msleep(300);
	sim_hid_stats(&s1, true);
	check(s1.transfers == 0U, "no reports while suspended (%u)", s1.transfers);
	check(hid8k_usb_state() == HID8K_USB_SUSPENDED, "the firmware's USB state is suspended");
	ret = uhc_bus_resume(uhc);
	check(ret == 0, "host resumes the bus: %d", ret);
	k_msleep(100);
	check(hid8k_usb_state() == HID8K_USB_CONFIGURED, "the firmware's USB state is configured");
	sim_hid_stats(&s1, true);
	check(s1.transfers > 0U && s1.seq_breaks == 0U,
	      "the stream resumes (%u reports) with seq continuous", s1.transfers);
	check(s1.busy == s0.busy && s1.refused == s0.refused,
	      "busy %u -> %u, refused %u -> %u (RESUME came before any completion)", s0.busy,
	      s1.busy, s0.refused, s1.refused);
	k_msleep(1000);
	stream("after resume", 500U, false);
}

static void step_suspend_race(void)
{
	const struct device *const uhc = sim_uhs_ctx->dev;
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	long stall0 = -1;
	long stall1 = -1;
	long t_resume_s;

	step("completions while the device has the bus marked suspended");
	cdc_mark = sim_cdc_line_count();
	if (next_stats_line(line, sizeof(line), 1500)) {
		stall0 = field(line, "stall=");
	}
	sim_hid_stats(&s0, true);
	/*
	 * SUSPEND reaches the device, then the host starts SOFs again without a RESUME: the device
	 * sees transfers complete while usbd_is_suspended() is true. On hardware this is the order
	 * the README describes (usbd_core.c handles completed transfers before a RESUME event that
	 * came first); here it is forced.
	 */
	(void)uhc_bus_suspend(uhc);
	k_msleep(50);
	(void)uhc_sof_enable(uhc);
	k_msleep(200);
	sim_hid_stats(&s1, true);
	check(s1.transfers == DEPTH,
	      "the %u queued reports complete, then nothing (%u): top_up() does not submit",
	      DEPTH, s1.transfers);
	k_msleep(1200);
	sim_hid_stats(&s1, true);
	check(s1.transfers == 0U,
	      "the stats thread's backstop kick does not act while suspended (%u reports)",
	      s1.transfers);

	(void)uhc_bus_resume(uhc);
	t_resume_s = (long)(sim_now_us() / 1000000);
	k_msleep(50);
	sim_hid_stats(&s1, false);
	check(s1.transfers > 0U && s1.seq_breaks == 0U,
	      "RESUME kicks the refill: the stream restarts (%u reports), seq continuous",
	      s1.transfers);
	check(s1.lag_short == DEPTH - 1U && s1.lag_bad == 0U,
	      "the refill primes the queue: %u report(s) name an older completion, then steady",
	      s1.lag_short);
	check(s1.busy - s0.busy == DEPTH,
	      "busy +%u: one per completion that found the bus marked suspended", s1.busy - s0.busy);
	check(s1.refused == s0.refused, "refused unchanged: no submit was tried");
	cdc_mark = sim_cdc_line_count();
	if (stats_line_from(t_resume_s + 1, line, sizeof(line), 2500)) {
		stall1 = field(line, "stall=");
		sim_print("  | %s\n", line);
	}
	check(stall0 >= 0 && stall1 == stall0 + 1,
	      "stall= %ld -> %ld: the refill kick found the queue empty once", stall0, stall1);
}

static void step_reconnect_host_side(void)
{
	const struct device *const uhc = sim_uhs_ctx->dev;
	const struct sim_hid_info *const hi = sim_hid_info();
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	const uint32_t binds0 = hi->binds;
	uint32_t last;
	bool ok;

	step("unplug and replug, as the Nucleo sees it (no VBUS sensing: suspend, then reset)");
	sim_hid_stats(&s0, false);
	last = s0.last_seq;
	sim_hid_stream_restart();
	/*
	 * The cable goes: the bus goes idle (the device suspends) and the host's port reports the
	 * device gone. uhc_submit_event() is the host controller driver's own way of saying so
	 * (drivers/usb/uhc/uhc_common.h); the virtual controller has no port model to do it.
	 */
	(void)uhc_bus_suspend(uhc);
	(void)uhc_submit_event(uhc, UHC_EVT_DEV_REMOVED, 0);
	check(wait_for(neither_bound, 500), "the host removed the device and its classes");
	k_msleep(500);
	check(hid8k_usb_state() == HID8K_USB_SUSPENDED, "the firmware's USB state is suspended");

	/* Plugged back in: the host sees the device again and enumerates it (bus reset first). */
	(void)uhc_submit_event(uhc, SIM_FS ? UHC_EVT_DEV_CONNECTED_FS : UHC_EVT_DEV_CONNECTED_HS, 0);
	ok = wait_for(both_bound, 3000);
	check(ok && hi->binds == binds0 + 1U, "the host enumerated the device again (bind %u)",
	      hi->binds);
	k_msleep(20);
	(void)sim_cdc_start();
	sim_hid_stats(&s1, true);
	(void)sim_hid_poll(true);
	k_msleep(100);
	sim_hid_stats(&s1, false);
	check(s1.stats > 0U && s1.first_seq == last + 1U + DEPTH,
	      "the stream restarts at seq %u after %u: the %u reports queued at the unplug were "
	      "cancelled, never sent",
	      s1.first_seq, last, DEPTH);
	check(s1.first_done_seq == last,
	      "its first report names completion %u, the last report the host received (%u): the "
	      "cancelled ones were not counted as completions",
	      s1.first_done_seq, last);
	check(s1.seq_breaks == 0U && s1.bad == 0U && s1.lag_short == 0U && s1.lag_bad == 0U,
	      "after the replug: seq continuous, reports well formed, pacing as before");
	check(s1.refused == s0.refused && s1.busy == s0.busy,
	      "refused %u -> %u, busy %u -> %u: the reset path marks the cancelled reports stale",
	      s0.refused, s1.refused, s0.busy, s1.busy);
	check(hid8k_usb_state() == HID8K_USB_CONFIGURED, "the firmware's USB state is configured");
}

static struct k_work detach_work;
static struct k_work attach_work;
static int detach_ret = -1;
static int attach_ret = -1;

/* On the system work queue, as the firmware's own VBUS path calls them (usb_device.c). */
static void detach_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	detach_ret = usbd_disable(hid8k_usbd_context());
}

static void attach_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	attach_ret = usbd_enable(hid8k_usbd_context());
}

static void step_reconnect_device_side(void)
{
	const struct sim_hid_info *const hi = sim_hid_info();
	struct sim_hid_stats s0;
	struct sim_hid_stats s1;
	const uint32_t binds0 = hi->binds;
	uint32_t last;
	bool ok;

	step("device-side detach and attach (usbd_disable, usbd_enable on the system work queue)");
	k_work_init(&detach_work, detach_handler);
	k_work_init(&attach_work, attach_handler);
	sim_hid_stats(&s0, false);
	last = s0.last_seq;
	sim_hid_stream_restart();
	(void)k_work_submit(&detach_work);
	ok = wait_for(neither_bound, 500);
	check(ok && detach_ret == 0, "usbd_disable: %d; the host removed the device", detach_ret);
	k_msleep(200);
	(void)k_work_submit(&attach_work);
	ok = wait_for(both_bound, 3000);
	check(ok && hi->binds == binds0 + 1U && attach_ret == 0,
	      "usbd_enable: %d; the host enumerated the device again (bind %u)", attach_ret,
	      hi->binds);
	k_msleep(20);
	(void)sim_cdc_start();
	sim_hid_stats(&s1, true);
	(void)sim_hid_poll(true);
	k_msleep(100);
	sim_hid_stats(&s1, false);
	check(s1.stats > 0U && s1.first_seq == last + 1U + DEPTH,
	      "the stream restarts at seq %u after %u (%u cancelled)", s1.first_seq, last, DEPTH);
	check(s1.seq_breaks == 0U && s1.bad == 0U && s1.lag_short == 0U && s1.lag_bad == 0U,
	      "after the attach: seq continuous, reports well formed, pacing as before");
	/*
	 * usbd_disable() runs usbd_config_set(0) in the caller's thread. usbd_ep_disable() calls
	 * k_yield() after cancelling each endpoint's buffers (usbd_endpoint.c), and the stack's
	 * "usbd" thread, K_PRIO_COOP(8), outranks the system work queue, K_PRIO_COOP(15) (priority
	 * -1), so it hands the cancelled reports to input_report_done before the classes are
	 * disabled: hid8k counts them as completions and its refill submits are refused (-ENODEV).
	 */
	check(s1.refused - s0.refused <= DEPTH && s1.first_done_seq >= last &&
		      s1.first_done_seq <= last + DEPTH,
	      "usbd_disable from the work queue: at most the %u cancelled reports miscounted "
	      "(refused +%u; the first report names %u, %u after the last one the host received)",
	      DEPTH, s1.refused - s0.refused, s1.first_done_seq, s1.first_done_seq - last);
	known_issue(s1.refused != s0.refused || s1.first_done_seq != last,
		    "usbd_disable from the work queue: the cancelled reports came back before "
		    "iface_ready(false): counted as completions (the first report names %u, the host "
		    "last received %u) and refused %u -> %u",
		    s1.first_done_seq, last, s0.refused, s1.refused);
}

static void step_final(void)
{
	struct baseline b;

	step("final undisturbed stream");
	k_msleep(1100); /* let a fresh stats window start */
	b = baseline_now();
	cdc_mark = sim_cdc_line_count();
	stream("final", 1000U, false);
	check_stats_line("final", false, b.cdc_dropped);
}

static void sim_test(void *p1, void *p2, void *p3)
{
	struct sim_cdc_stats c;
	int fd_cdc = -1;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	sim_print("hid8k-sim: Zephyr USB host stack on the virtual host controller (%s), "
	       "the firmware on the virtual device controller at %s speed; frame period %u us "
	       "(simulated time)\n",
	       IS_ENABLED(CONFIG_HID8K_SIM_UHC_HS_FIX) ? "the simulation's high-speed copy"
						       : "Zephyr v4.5.0's own",
	       SPEED_NAME, PERIOD_US);

	step("boot and enumeration");
	check(wait_for(both_bound, 3000), "the host bound the HID and CDC ACM functions");
	if (!both_bound()) {
		goto out;
	}

	fd_cdc = open_host_file(opt_cdc_log);
	sim_cdc_log(fd_cdc);

	check_enumeration();

	(void)sim_cdc_start();
	(void)sim_hid_poll(true);
	k_msleep(1200);

	step_stream();
	step_commands();
	step_heavy();
	step_cdc_backlog();
	step_keyboard();
	step_host_stops();
	step_suspend();
	step_suspend_race();
	step_reconnect_host_side();
	step_reconnect_device_side();
	step_final();

	sim_cdc_stats(&c);
	sim_print("\nhid8k-sim: CDC read %u bytes, %u lines (%u stats, %u filler), sent %u bytes\n",
	       c.rx_bytes, c.lines, c.stats_lines, c.fill_lines, c.tx_bytes);
	if (fd_cdc >= 0) {
		sim_cdc_log(-1);
		nsi_host_close(fd_cdc);
	}

out:
	check(n_anomalies == 0U, "no anomalies (%u)", n_anomalies);
	sim_print("\nhid8k-sim: %s: %u checks, %u failed, %u known issues, %u anomalies, "
	       "%lld ms simulated, frame %u us, %s speed\n",
	       n_failed == 0U ? "PASS" : "FAIL", n_checks, n_failed, n_known, n_anomalies,
	       sim_now_us() / 1000, PERIOD_US, SPEED_NAME);
	k_msleep(10); /* let the log drain */
	posix_exit(n_failed == 0U ? 0 : 1);
}

K_THREAD_DEFINE(sim_test_thread, 8192, sim_test, NULL, NULL, NULL, K_PRIO_COOP(10), 0, 0);
