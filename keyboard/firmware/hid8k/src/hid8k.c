/*
 * hid8k: one HID interface (NKRO keyboard, report ID 1, plus a vendor stats report, ID 2)
 * streamed at one report per high-speed microframe, paced from input_report_done.
 *
 * Threading. Everything that touches the report buffers and the counters below runs in the
 * USB device stack's thread ("usbd", cooperative, K_PRIO_COOP(8), usbd_core.c): the
 * iface_ready, input_report_done, get_report and idle callbacks (usbd_hid.c calls them from
 * usbd_hid_request() and the control handlers). The one exception is the refill kick
 * (kick_handler()), which runs on the system work queue: that thread is cooperative too
 * (BUILD_ASSERT below), and on this single core two cooperative threads never interleave
 * unless one blocks, which none of this code does. Other threads only read through
 * hid8k_take_snapshot(), which holds the scheduler lock while it copies, and set the atomics
 * at the top.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <errno.h>
#include <string.h>

#if !defined(CONFIG_HID8K_SIM)
#include <soc.h>
#endif
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/input/input.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>
#include <zephyr/usb/class/usbd_hid.h>
#include <zephyr/usb/usbd.h>

#include "cdc_console.h"
#include "hid8k.h"
#include "hid8k_report.h"

LOG_MODULE_REGISTER(hid8k, LOG_LEVEL_INF);

#define DEPTH CONFIG_HID8K_QUEUE_DEPTH

/*
 * usbd_hid calls input_report_done() before it frees the completed transfer's net_buf
 * (usbd_hid_request(), usbd_hid.c), and hid_device_submit_report() takes a net_buf from the
 * same per-instance pool, so the pool needs one buffer more than the reports kept queued.
 */
BUILD_ASSERT(CONFIG_USBD_HID_IN_BUF_COUNT >= DEPTH + 1,
	     "CONFIG_USBD_HID_IN_BUF_COUNT must be at least CONFIG_HID8K_QUEUE_DEPTH + 1");

#define HID_NODE DT_INST(0, zephyr_hid_device)
BUILD_ASSERT(DT_PROP(HID_NODE, in_polling_period_us) == HID8K_NOMINAL_US,
	     "the HID node must set in-polling-period-us = <125> (bInterval 1 at high speed)");
BUILD_ASSERT(DT_PROP(HID_NODE, in_report_size) == HID8K_STATS_SIZE,
	     "in-report-size must be 64 so wMaxPacketSize is 64 (no alternate setting)");
BUILD_ASSERT(!IS_ENABLED(CONFIG_SMP), "the threading argument above assumes one core");
BUILD_ASSERT(CONFIG_SYSTEM_WORKQUEUE_PRIORITY < 0,
	     "the refill kick must run on a cooperative work queue, like the usbd thread");

#if defined(CONFIG_HID8K_SIM)
/* native_sim (sim/): Zephyr's cycle counter, k_cycle_get_32(), stands in for the DWT. */
#define CPU_HZ CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC
#else
/* The cycle counter runs at HCLK. */
#define RCC_NODE DT_NODELABEL(rcc)
#define CPU_HZ   (DT_PROP(RCC_NODE, clock_frequency) / DT_PROP(RCC_NODE, ahb_prescaler))
#endif

/* The button that sends the keyboard report: the board's sw0 (the Nucleo's blue USER button). */
#define BUTTON_CODE DT_PROP(DT_ALIAS(sw0), zephyr_code)

static const uint8_t report_desc[] = {
	/* Report ID 1: NKRO keyboard, a modifier byte and a bitmap of usages 0x00..0xDF. */
	HID_USAGE_PAGE(HID_USAGE_GEN_DESKTOP),
	HID_USAGE(HID_USAGE_GEN_DESKTOP_KEYBOARD),
	HID_COLLECTION(HID_COLLECTION_APPLICATION),
		HID_REPORT_ID(HID8K_REPORT_ID_KBD),
		HID_USAGE_PAGE(HID_USAGE_GEN_KEYBOARD),
		HID_USAGE_MIN8(0xE0),
		HID_USAGE_MAX8(0xE7),
		HID_LOGICAL_MIN8(0),
		HID_LOGICAL_MAX8(1),
		HID_REPORT_SIZE(1),
		HID_REPORT_COUNT(8),
		/* Input (Data, Var, Abs): the eight modifiers */
		HID_INPUT(0x02),
		HID_USAGE_MIN8(0x00),
		HID_USAGE_MAX8(HID8K_NKRO_BITS - 1U),
		HID_REPORT_COUNT(HID8K_NKRO_BITS),
		/* Input (Data, Var, Abs): one bit per key */
		HID_INPUT(0x02),
	HID_END_COLLECTION,

	/* Report ID 2: 63 vendor-defined bytes, the stats record (hid8k_report.h). */
	HID_USAGE_PAGE16(0xFF00),
	HID_USAGE(HID8K_VENDOR_USAGE),
	HID_COLLECTION(HID_COLLECTION_APPLICATION),
		HID_REPORT_ID(HID8K_REPORT_ID_STATS),
		HID_USAGE(HID8K_VENDOR_USAGE_DATA),
		HID_LOGICAL_MIN8(0),
		HID_LOGICAL_MAX16(0xFF, 0x00),
		HID_REPORT_SIZE(8),
		HID_REPORT_COUNT(HID8K_STATS_SIZE - 1U),
		/* Input (Data, Var, Abs) */
		HID_INPUT(0x02),
	HID_END_COLLECTION,
};

BUILD_ASSERT(HID8K_VENDOR_USAGE_PAGE == 0xFF00U, "report_desc spells the vendor page out");

/*
 * Report buffers. usbd_hid sends straight from them (net_buf_alloc_with_data(), zero copy),
 * so a buffer stays untouched from its submit until its input_report_done.
 */
static uint8_t __aligned(UDC_BUF_ALIGN) stats_buf[DEPTH][UDC_ROUND_UP(HID8K_STATS_SIZE)];
static uint8_t __aligned(UDC_BUF_ALIGN) kbd_buf[UDC_ROUND_UP(HID8K_KBD_SIZE)];

/* Set from other threads. */
static atomic_t button_down; /* input callback (system workqueue) */
static atomic_t cdc_heavy;   /* stats thread */

/* Owned by the usbd thread. */
static struct {
	const struct device *dev;
	struct usbd_context *uds_ctx;
	bool streaming;
	bool high_speed;
	unsigned int outstanding;      /* reports submitted and not yet completed */
	bool stats_queued[DEPTH];
	bool kbd_queued;
	/* Queued when the interface went down: they come back cancelled, not sent. */
	bool stats_stale[DEPTH];
	bool kbd_stale;
	uint32_t kbd_seq;              /* seq of the keyboard report in flight */
	bool kbd_sent_down;            /* F24 state in the last keyboard report submitted */
	uint32_t next_seq;
	bool have_prev_done;
	uint32_t prev_done_cyc;
	uint32_t last_done_seq;
	uint32_t last_done_cyc;
	uint16_t last_done_fn;
	uint32_t last_cost;
	int last_err;
	int last_stats_slot;
	/* Monotonic since boot, carried in every stats report. */
	uint32_t refused;
	uint32_t busy;
	uint32_t late;
	uint32_t kbd_count;
	uint32_t kicks;                /* refill kicks that found the queue empty */
	/* Since boot or the last reset. */
	uint32_t max_interval;
	uint32_t idle[3];              /* Set Idle durations per report ID, ms (stored only) */
} st;

static struct hid8k_stats win;
static struct hid8k_stats cum;

static uint32_t late_cycles;
static uint32_t bucket_cycles;

static inline uint32_t cycles_now(void)
{
#if defined(CONFIG_HID8K_SIM)
	return k_cycle_get_32();
#else
	return DWT->CYCCNT;
#endif
}

static inline uint16_t frame_number(void)
{
#if defined(CONFIG_HID8K_FRAME_NUMBER)
	/*
	 * Outside the USB stack: the stack does not expose the (micro)frame number, so this reads
	 * the OTG_HS core's device status register directly. Read-only, no side effects.
	 */
	const USB_OTG_DeviceTypeDef *const otg_dev =
		(const USB_OTG_DeviceTypeDef *)(DT_REG_ADDR(DT_NODELABEL(usbotg_hs)) +
						 USB_OTG_DEVICE_BASE);

	return (uint16_t)((otg_dev->DSTS & USB_OTG_DSTS_FNSOF_Msk) >> USB_OTG_DSTS_FNSOF_Pos);
#else
	return 0U;
#endif
}

static void stats_clear(struct hid8k_stats *s)
{
	memset(s, 0, sizeof(*s));
	s->interval_min = UINT32_MAX;
	s->cost_min = UINT32_MAX;
}

static void stats_add_interval(struct hid8k_stats *s, uint32_t d, uint32_t bucket)
{
	s->intervals++;
	s->interval_sum += d;
	s->interval_min = MIN(s->interval_min, d);
	s->interval_max = MAX(s->interval_max, d);
	s->hist[bucket]++;
	if (d > late_cycles) {
		s->late++;
	}
}

static void stats_add_cost(struct hid8k_stats *s, uint32_t cost)
{
	s->submits++;
	s->cost_sum += cost;
	s->cost_min = MIN(s->cost_min, cost);
	s->cost_max = MAX(s->cost_max, cost);
}

static uint8_t stats_flags(void)
{
	uint8_t flags = 0U;

	if (IS_ENABLED(CONFIG_HID8K_FRAME_NUMBER)) {
		flags |= HID8K_FLAG_FN_VALID;
	}
	if (atomic_get(&cdc_heavy) != 0) {
		flags |= HID8K_FLAG_CDC_HEAVY;
	}
	if (st.high_speed) {
		flags |= HID8K_FLAG_HIGH_SPEED;
	}

	return flags;
}

/* Fill a stats report; t_submit and fn_submit are written by the caller just before submit. */
static void stats_build(uint8_t *const b, const uint32_t seq)
{
	b[HID8K_OFF_ID] = HID8K_REPORT_ID_STATS;
	b[HID8K_OFF_FORMAT] = HID8K_FORMAT;
	b[HID8K_OFF_FLAGS] = stats_flags();
	b[HID8K_OFF_DEPTH] = DEPTH;
	sys_put_le32(seq, &b[HID8K_OFF_SEQ]);
	sys_put_le32(st.last_done_seq, &b[HID8K_OFF_DONE_SEQ]);
	sys_put_le32(st.last_done_cyc, &b[HID8K_OFF_T_DONE]);
	sys_put_le32(st.last_cost, &b[HID8K_OFF_SUBMIT_COST]);
	sys_put_le32(st.refused, &b[HID8K_OFF_REFUSED]);
	sys_put_le32(st.busy, &b[HID8K_OFF_BUSY]);
	sys_put_le32(st.late, &b[HID8K_OFF_LATE]);
	sys_put_le32(st.kbd_count, &b[HID8K_OFF_KBD_COUNT]);
	sys_put_le32(CPU_HZ, &b[HID8K_OFF_CPU_HZ]);
	sys_put_le16(st.last_done_fn, &b[HID8K_OFF_FN_DONE]);
	sys_put_le32(st.max_interval, &b[HID8K_OFF_MAX_INTERVAL]);
	sys_put_le32(k_uptime_get_32(), &b[HID8K_OFF_UPTIME_MS]);
	sys_put_le32(cdc_console_queued(), &b[HID8K_OFF_CDC_BYTES]);
	sys_put_le32(cdc_console_dropped(), &b[HID8K_OFF_CDC_DROPPED]);
}

static void kbd_build(uint8_t *const b, const bool down)
{
	memset(b, 0, HID8K_KBD_SIZE);
	b[0] = HID8K_REPORT_ID_KBD;
	/* b[1]: no modifiers. The bitmap starts at b[2] with usage 0x00. */
	if (down) {
		b[2U + HID8K_KEY_F24 / 8U] = (uint8_t)BIT(HID8K_KEY_F24 % 8U);
	}
}

/* Submit one report and account for it. Returns the submit call's result. */
static int submit(const uint8_t *const report, const uint16_t len, const uint32_t t0)
{
	int ret;
	uint32_t cost;

	ret = hid_device_submit_report(st.dev, len, report);
	cost = cycles_now() - t0;

	if (ret != 0) {
		st.refused++;
		st.last_err = ret;
		win.refused++;
		cum.refused++;
		return ret;
	}

	st.last_cost = cost;
	st.next_seq++;
	st.outstanding++;
	stats_add_cost(&win, cost);
	stats_add_cost(&cum, cost);

	return 0;
}

static int submit_kbd(const bool down)
{
	const uint32_t seq = st.next_seq;
	uint32_t t0;
	int ret;

	kbd_build(kbd_buf, down);
	st.kbd_queued = true;
	t0 = cycles_now();
	ret = submit(kbd_buf, HID8K_KBD_SIZE, t0);
	if (ret != 0) {
		st.kbd_queued = false;
		return ret;
	}

	st.kbd_seq = seq;
	st.kbd_sent_down = down;
	st.kbd_count++;
	win.kbd++;
	cum.kbd++;

	return 0;
}

static int submit_stats(void)
{
	uint8_t *b;
	uint32_t t0;
	int slot;
	int ret;

	for (slot = 0; slot < DEPTH; slot++) {
		if (!st.stats_queued[slot]) {
			break;
		}
	}

	if (slot == DEPTH) {
		st.busy++;
		win.busy++;
		cum.busy++;
		return -EBUSY;
	}

	b = stats_buf[slot];
	stats_build(b, st.next_seq);
	st.stats_queued[slot] = true;
	sys_put_le16(frame_number(), &b[HID8K_OFF_FN_SUBMIT]);
	t0 = cycles_now();
	sys_put_le32(t0, &b[HID8K_OFF_T_SUBMIT]);
	ret = submit(b, HID8K_STATS_SIZE, t0);
	if (ret != 0) {
		st.stats_queued[slot] = false;
		return ret;
	}

	st.last_stats_slot = slot;

	return 0;
}

/* Keep DEPTH reports queued. A keyboard report takes the place of a stats report. */
static void top_up(void)
{
	/*
	 * usbd_ep_enqueue() refuses every IN transfer with -EPERM while the stack has the bus
	 * marked suspended (subsys/usb/device_next/usbd_endpoint.c:145-149). A completion can
	 * be handled before the RESUME event that precedes it (usbd_core.c drains the transfer
	 * list first, usbd_event_handler()), so do not submit then, and count it as busy (the
	 * stats report has no spare field, and the run must not pass silently): the RESUME
	 * message kicks a refill (usb_device.c), and the stats thread kicks once per period as a
	 * backstop.
	 */
	if (st.uds_ctx != NULL && usbd_is_suspended(st.uds_ctx)) {
		if (st.streaming && st.outstanding < DEPTH) {
			st.busy++;
			win.busy++;
			cum.busy++;
		}
		return;
	}

	while (st.streaming && st.outstanding < DEPTH) {
		const bool down = atomic_get(&button_down) != 0;
		int ret;

		if (down != st.kbd_sent_down && !st.kbd_queued) {
			ret = submit_kbd(down);
		} else {
			ret = submit_stats();
		}

		if (ret != 0) {
			/* Try again at the next completion; never spin here. */
			break;
		}
	}
}

static void record_completion(const uint32_t now, const uint32_t seq)
{
	if (st.have_prev_done) {
		const uint32_t d = now - st.prev_done_cyc;
		const uint32_t bucket = MIN(d / bucket_cycles, HID8K_HIST_BUCKETS);

		stats_add_interval(&win, d, bucket);
		stats_add_interval(&cum, d, bucket);
		if (d > late_cycles) {
			st.late++;
		}
		st.max_interval = MAX(st.max_interval, d);
	}

	st.have_prev_done = true;
	st.prev_done_cyc = now;
	st.last_done_seq = seq;
	st.last_done_cyc = now;
	st.last_done_fn = frame_number();
	win.completions++;
	cum.completions++;
}

static void hid8k_input_report_done(const struct device *dev, const uint8_t *const report)
{
	const uint32_t now = cycles_now();
	bool stale;
	uint32_t seq;

	ARG_UNUSED(dev);

	if (report == kbd_buf) {
		seq = st.kbd_seq;
		stale = st.kbd_stale;
		st.kbd_queued = false;
		st.kbd_stale = false;
	} else {
		int slot;

		for (slot = 0; slot < DEPTH; slot++) {
			if (report == stats_buf[slot]) {
				break;
			}
		}

		if (slot == DEPTH) {
			return;
		}

		seq = sys_get_le32(&stats_buf[slot][HID8K_OFF_SEQ]);
		stale = st.stats_stale[slot];
		st.stats_queued[slot] = false;
		st.stats_stale[slot] = false;
	}

	if (st.outstanding > 0U) {
		st.outstanding--;
	}

	/*
	 * Disabling the interface dequeues its endpoint, and usbd_hid hands each cancelled
	 * transfer back through this callback (it does not pass the error on). Those are not
	 * completions: free the buffer and, if streaming again already, refill the queue.
	 */
	if (!stale && st.streaming) {
		record_completion(now, seq);
	}

	top_up();
}

static void hid8k_iface_ready(const struct device *dev, const bool ready)
{
	ARG_UNUSED(dev);

	if (ready) {
		st.high_speed = (st.uds_ctx != NULL) &&
				(usbd_bus_speed(st.uds_ctx) == USBD_SPEED_HS);
		st.have_prev_done = false;
		/* A new configuration starts with no key down on the host's side. */
		st.kbd_sent_down = false;
		st.streaming = true;
		/* Prime the queue; from here on input_report_done keeps it full. */
		top_up();
	} else {
		st.streaming = false;
		for (int slot = 0; slot < DEPTH; slot++) {
			st.stats_stale[slot] = st.stats_queued[slot];
		}
		st.kbd_stale = st.kbd_queued;
	}
}

static int hid8k_get_report_size(const struct device *dev, const uint8_t type, const uint8_t id)
{
	ARG_UNUSED(dev);

	if (type != HID_REPORT_TYPE_INPUT) {
		return 0;
	}

	switch (id) {
	case HID8K_REPORT_ID_KBD:
		return HID8K_KBD_SIZE;
	case HID8K_REPORT_ID_STATS:
		return HID8K_STATS_SIZE;
	default:
		return 0;
	}
}

static int hid8k_get_report(const struct device *dev, const uint8_t type, const uint8_t id,
			    const uint16_t len, uint8_t *const buf)
{
	uint8_t tmp[HID8K_STATS_SIZE];
	uint16_t n;

	ARG_UNUSED(dev);

	if (type != HID_REPORT_TYPE_INPUT) {
		return -ENOTSUP;
	}

	switch (id) {
	case HID8K_REPORT_ID_KBD:
		kbd_build(tmp, st.kbd_sent_down);
		n = HID8K_KBD_SIZE;
		break;
	case HID8K_REPORT_ID_STATS:
		if (st.last_stats_slot >= 0) {
			/* The most recently submitted stats report, as sent. */
			memcpy(tmp, stats_buf[st.last_stats_slot], HID8K_STATS_SIZE);
		} else {
			/*
			 * None sent yet (a host may ask while probing): answer with a valid
			 * report rather than a protocol stall. seq is the next one to be used.
			 */
			stats_build(tmp, st.next_seq);
			sys_put_le32(cycles_now(), &tmp[HID8K_OFF_T_SUBMIT]);
			sys_put_le16(frame_number(), &tmp[HID8K_OFF_FN_SUBMIT]);
		}
		n = HID8K_STATS_SIZE;
		break;
	default:
		return -ENOTSUP;
	}

	n = MIN(n, len);
	memcpy(buf, tmp, n);

	return n;
}

static void hid8k_set_idle(const struct device *dev, const uint8_t id, const uint32_t duration)
{
	ARG_UNUSED(dev);

	/* Stored for Get Idle only: the stream does not depend on the idle rate. */
	if (id < ARRAY_SIZE(st.idle)) {
		st.idle[id] = duration;
	}
}

static uint32_t hid8k_get_idle(const struct device *dev, const uint8_t id)
{
	ARG_UNUSED(dev);

	return (id < ARRAY_SIZE(st.idle)) ? st.idle[id] : 0U;
}

static const struct hid_device_ops hid8k_ops = {
	.iface_ready = hid8k_iface_ready,
	.get_report_size = hid8k_get_report_size,
	.get_report = hid8k_get_report,
	.set_idle = hid8k_set_idle,
	.get_idle = hid8k_get_idle,
	.input_report_done = hid8k_input_report_done,
};

static void hid8k_input_cb(struct input_event *evt, void *user_data)
{
	ARG_UNUSED(user_data);

	if (evt->type == INPUT_EV_KEY && evt->code == BUTTON_CODE) {
		atomic_set(&button_down, evt->value != 0 ? 1 : 0);
	}
}

INPUT_CALLBACK_DEFINE(NULL, hid8k_input_cb, NULL);

/*
 * The refill kick. Normally every completion refills the queue, so it never runs dry. If the
 * last outstanding report completes without a refill (top_up() skipped it because the bus
 * was still marked suspended, or the submit was refused), no completion is left to retry it
 * and the stream would stop for good. This work item restarts it. It acts only when nothing
 * is outstanding, so it cannot add to a queue the completions are already keeping full.
 */
static void kick_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	if (st.streaming && st.outstanding == 0U &&
	    !(st.uds_ctx != NULL && usbd_is_suspended(st.uds_ctx))) {
		st.kicks++;
		top_up();
	}
}

static K_WORK_DEFINE(kick_work, kick_handler);

void hid8k_kick(void)
{
	(void)k_work_submit(&kick_work);
}

uint32_t hid8k_cpu_hz(void)
{
	return CPU_HZ;
}

void hid8k_cycle_counter_keepalive(void)
{
#if !defined(CONFIG_HID8K_SIM)
	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
#endif
}

void hid8k_set_cdc_heavy(const bool heavy)
{
	atomic_set(&cdc_heavy, heavy ? 1 : 0);
}

void hid8k_take_snapshot(struct hid8k_snapshot *const snap, const bool reset_cum)
{
	k_sched_lock();

	snap->cycles = cycles_now();
	snap->uptime_ms = k_uptime_get();
	snap->win = win;
	snap->cum = cum;
	snap->next_seq = st.next_seq;
	snap->outstanding = st.outstanding;
	snap->kicks = st.kicks;
	snap->last_err = st.last_err;
	snap->streaming = st.streaming;
	snap->high_speed = st.high_speed;

	stats_clear(&win);
	if (reset_cum) {
		stats_clear(&cum);
		st.max_interval = 0U;
	}

	k_sched_unlock();
}

int hid8k_init(struct usbd_context *const uds_ctx)
{
	int ret;

#if !defined(CONFIG_HID8K_SIM)
	/* The DWT cycle counter: the timestamps in every stats report. */
	DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
	if ((DWT->CTRL & DWT_CTRL_NOCYCCNT_Msk) != 0U) {
		LOG_ERR("DWT has no cycle counter: no timestamps");
		return -ENOTSUP;
	}
	DWT->CYCCNT = 0U;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
#endif

	late_cycles = (uint32_t)(((uint64_t)CPU_HZ * HID8K_LATE_US_X10) / 10000000U);
	bucket_cycles = (uint32_t)(((uint64_t)CPU_HZ * HID8K_HIST_BUCKET_US_X10) / 10000000U);

	stats_clear(&win);
	stats_clear(&cum);
	st.uds_ctx = uds_ctx;
	st.last_stats_slot = -1;

	st.dev = DEVICE_DT_GET(HID_NODE);
	if (!device_is_ready(st.dev)) {
		LOG_ERR("HID device not ready");
		return -ENODEV;
	}

	ret = hid_device_register(st.dev, report_desc, sizeof(report_desc), &hid8k_ops);
	if (ret != 0) {
		LOG_ERR("hid_device_register failed: %d", ret);
	}

	return ret;
}
