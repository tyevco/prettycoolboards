/*
 * hid8k: 8 kHz HID proof for the NUCLEO-U5A5ZJ-Q (keyboard/docs/mcu.md, condition 2).
 *
 * main() brings the device up, then becomes the stats thread: once per log period it takes a
 * snapshot of the firmware-side statistics and prints one line over the CDC ACM console, and
 * in heavy mode it also streams filler text there to load the CDC path.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#if !defined(CONFIG_HID8K_SIM)
#include <stm32_ll_bus.h>
#include <stm32_ll_system.h>
#endif

#include "cdc_console.h"
#include "hid8k.h"
#include "hid8k_report.h"
#include "usb_device.h"

#define HEAVY_TICK_MS  10
#define IDLE_TICK_MS   100
#define MIRROR_MIN_MS  1000
#define FILL_LINE_LEN  64U

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET_OR(DT_ALIAS(led0), gpios, {0});

/* Requests from the CDC command callback (CDC work queue), served by the stats thread. */
static atomic_t req_heavy = ATOMIC_INIT(-1); /* -1 none, 0 normal, 1 heavy */
static atomic_t req_reset;
static atomic_t req_hist;
static atomic_t req_help;
static atomic_t req_unknown;

/* Large enough for the cumulative histogram with every bucket at its widest (about 830 B). */
static char line[1024];

static void on_command(const char *const cmd)
{
	if (strcmp(cmd, "heavy") == 0) {
		atomic_set(&req_heavy, 1);
	} else if (strcmp(cmd, "normal") == 0) {
		atomic_set(&req_heavy, 0);
	} else if (strcmp(cmd, "reset") == 0) {
		atomic_set(&req_reset, 1);
	} else if (strcmp(cmd, "hist") == 0) {
		atomic_set(&req_hist, 1);
	} else if (strcmp(cmd, "help") == 0 || strcmp(cmd, "?") == 0) {
		atomic_set(&req_help, 1);
	} else {
		atomic_inc(&req_unknown);
	}
}

static void cdc_puts(const char *const s)
{
	(void)cdc_console_write(s, strlen(s));
}

/*
 * The window measured by the cycle counter must match the one measured by the kernel's
 * uptime (both run from HCLK): if not, the counter stopped (a debug probe rewrote DEMCR) or
 * cpu_hz is wrong, and every timestamp in the stats reports is suspect. Tolerance: 2 ms for
 * the uptime's millisecond steps, plus 1 %.
 */
static bool cycles_consistent(const uint32_t window_cycles, const int64_t window_ms,
			      const uint32_t cpu_hz)
{
	const int64_t cyc_ms = (int64_t)window_cycles / (int64_t)(cpu_hz / 1000U);
	const int64_t diff = cyc_ms > window_ms ? cyc_ms - window_ms : window_ms - cyc_ms;

	return diff <= 2 + window_ms / 100;
}

/* Microseconds x 10 from cycles. */
static uint32_t us_x10(const uint64_t cycles, const uint32_t cpu_hz)
{
	return (uint32_t)((cycles * 10000000ULL) / cpu_hz);
}

static const char *usb_state_name(const enum hid8k_usb_state s)
{
	switch (s) {
	case HID8K_USB_CONFIGURED:
		return "cfg";
	case HID8K_USB_SUSPENDED:
		return "susp";
	case HID8K_USB_ADDRESSED:
		return "addr";
	default:
		return "dflt";
	}
}

/* Sum histogram buckets [lo, hi) (bucket indices). */
static uint32_t hist_sum(const struct hid8k_stats *const s, const unsigned int lo,
			 const unsigned int hi)
{
	uint32_t n = 0U;

	for (unsigned int i = lo; i < hi && i < HID8K_HIST_SLOTS; i++) {
		n += s->hist[i];
	}

	return n;
}

static int format_stats(const struct hid8k_snapshot *const snap, const uint32_t window_cycles,
			const bool heavy, const bool cyc_ok)
{
	const struct hid8k_stats *const w = &snap->win;
	const uint32_t cpu_hz = hid8k_cpu_hz();
	const uint32_t rate_x10 = window_cycles == 0U ? 0U :
		(uint32_t)(((uint64_t)w->completions * cpu_hz * 10U) / window_cycles);
	const uint32_t imin = w->intervals ? us_x10(w->interval_min, cpu_hz) : 0U;
	const uint32_t iavg = w->intervals ? us_x10(w->interval_sum / w->intervals, cpu_hz) : 0U;
	const uint32_t imax = w->intervals ? us_x10(w->interval_max, cpu_hz) : 0U;
	const uint32_t cmin = w->submits ? w->cost_min : 0U;
	const uint32_t cavg = w->submits ? (uint32_t)(w->cost_sum / w->submits) : 0U;
	const char *note = "";

	if (!cyc_ok) {
		note = " CYCCNT-MISMATCH";
	} else if (snap->streaming && w->completions == 0U) {
		note = " NO-COMPLETIONS";
	} else if (!snap->streaming) {
		note = " not-streaming";
	}

	/* Bucket edges at 12.5 us: 8 = 100 us, 12 = 150, 15 = 187.5, 20 = 250. */
	return snprintk(line, sizeof(line),
			"hid8k t=%us usb=%s %s rate=%u.%u/s int_us=%u.%u/%u.%u/%u.%u "
			"late=%u hist[<100:%u 100-150:%u 150-187.5:%u 187.5-250:%u >=250:%u] "
			"submit_cyc=%u/%u/%u refused=%u busy=%u err=%d kbd=%u out=%u stall=%u "
			"cdc=%s q=%u drop=%u pend=%u%s\r\n",
			k_uptime_get_32() / 1000U, usb_state_name(hid8k_usb_state()),
			snap->high_speed ? "hs" : "fs", rate_x10 / 10U, rate_x10 % 10U,
			imin / 10U, imin % 10U, iavg / 10U, iavg % 10U, imax / 10U, imax % 10U,
			w->late, hist_sum(w, 0, 8), hist_sum(w, 8, 12), hist_sum(w, 12, 15),
			hist_sum(w, 15, 20), hist_sum(w, 20, HID8K_HIST_SLOTS), cmin, cavg,
			w->cost_max, w->refused, w->busy, snap->last_err, w->kbd, snap->outstanding,
			snap->kicks, heavy ? "heavy" : "normal", cdc_console_queued(), cdc_console_dropped(),
			cdc_console_pending(), note);
}

static void print_hist(const struct hid8k_snapshot *const snap)
{
	const struct hid8k_stats *const c = &snap->cum;
	const uint32_t cpu_hz = hid8k_cpu_hz();
	int len;

	len = snprintk(line, sizeof(line),
		       "hid8k hist since reset: n=%u late=%u max_us=%u.%u buckets(us:count)",
		       c->intervals, c->late,
		       c->intervals ? us_x10(c->interval_max, cpu_hz) / 10U : 0U,
		       c->intervals ? us_x10(c->interval_max, cpu_hz) % 10U : 0U);

	for (unsigned int i = 0; i < HID8K_HIST_SLOTS && len > 0 && len < (int)sizeof(line) - 32;
	     i++) {
		const uint32_t lo_x10 = i * HID8K_HIST_BUCKET_US_X10;

		if (c->hist[i] == 0U) {
			continue;
		}

		len += snprintk(&line[len], sizeof(line) - (size_t)len, " %s%u.%u:%u",
				i == HID8K_HIST_BUCKETS ? ">=" : "", lo_x10 / 10U, lo_x10 % 10U,
				c->hist[i]);
	}

	if (len > 0 && len < (int)sizeof(line) - 3) {
		len += snprintk(&line[len], sizeof(line) - (size_t)len, "\r\n");
		cdc_puts(line);
	}
}

static void print_help(void)
{
	cdc_puts("hid8k commands (one per line): heavy | normal | reset | hist | help\r\n");
	snprintk(line, sizeof(line),
		 "hid8k config: queue_depth=%d log_period_ms=%d heavy_bps=%d chunk=%d "
		 "frame_number=%s cpu_hz=%u\r\n",
		 CONFIG_HID8K_QUEUE_DEPTH, CONFIG_HID8K_LOG_PERIOD_MS, CONFIG_HID8K_CDC_HEAVY_BPS,
		 CONFIG_HID8K_CDC_CHUNK, IS_ENABLED(CONFIG_HID8K_FRAME_NUMBER) ? "on" : "off",
		 hid8k_cpu_hz());
	cdc_puts(line);
}

/* Heavy mode: owed bytes of filler, in fixed-length lines the host can count. */
static void write_filler(uint32_t bytes, uint32_t *const fill_seq)
{
	char fill[FILL_LINE_LEN + 1U];

	while (bytes >= FILL_LINE_LEN) {
		int n = snprintk(fill, sizeof(fill), "~fill %08x ", *fill_seq);

		memset(&fill[n], '.', FILL_LINE_LEN - 2U - (uint32_t)n);
		fill[FILL_LINE_LEN - 2U] = '\r';
		fill[FILL_LINE_LEN - 1U] = '\n';
		(void)cdc_console_write(fill, FILL_LINE_LEN);
		(*fill_seq)++;
		bytes -= FILL_LINE_LEN;
	}
}

/*
 * RM0456 Rev 7 section 15.2.3 brings the HS PHY up as: clocks on, CLKSEL, then
 * SYSCFG_OTGHSPHYTUNER2 with COMPDISTUNE = 010 (+5.9 %) and SQRXTUNE = 000 (+15 %), then EN.
 * Zephyr v4.5.0's stm32_u5otghs_phy_enable() (called from udc_stm32_init(), which usbd_init()
 * reaches) writes CLKSEL and EN but never TUNER2. With CONFIG_HID8K_PHY_TUNER2 the two fields
 * are written here, before usbd_init(). The LL setters modify only their own bits: TUNER2's
 * bits 31:15 are reserved and must keep their reset value, so never a 32-bit write.
 */
#if !defined(CONFIG_HID8K_SIM)
static void phy_tuner2_apply(void)
{
	if (!IS_ENABLED(CONFIG_HID8K_PHY_TUNER2)) {
		return;
	}
	LL_APB3_GRP1_EnableClock(LL_APB3_GRP1_PERIPH_SYSCFG);
	LL_SYSCFG_SetOTGPHYDisconnectThresholdAdjustment(LL_SYSCFG_OTGHSPHY_DISCONNECT_5_9PERCENT);
	LL_SYSCFG_SetOTGPHYSquelchThresholdAdjustment(LL_SYSCFG_OTGHSPHY_SQUELCH_15PERCENT);
}

/*
 * After usbd_init() the SYSCFG clock is on in both builds (the PHY driver enables it), so the
 * register reads back.
 */
static void phy_tuner2_report(void)
{
	const uint32_t tuner2 = SYSCFG->OTGHSPHYTUNER2;

	printk("hid8k: OTG_HS PHY TUNER2 = 0x%08x (COMPDISTUNE %u, SQRXTUNE %u; %s)\n",
	       (unsigned int)tuner2,
	       (unsigned int)((tuner2 & SYSCFG_OTGHSPHYTUNER2_COMPDISTUNE) >>
			      SYSCFG_OTGHSPHYTUNER2_COMPDISTUNE_Pos),
	       (unsigned int)((tuner2 & SYSCFG_OTGHSPHYTUNER2_SQRXTUNE) >>
			      SYSCFG_OTGHSPHYTUNER2_SQRXTUNE_Pos),
	       IS_ENABLED(CONFIG_HID8K_PHY_TUNER2) ? "RM0456 recommended values written"
						   : "Zephyr default, not written");
}
#else
/* native_sim (sim/): there is no PHY to tune. */
static void phy_tuner2_apply(void)
{
}

static void phy_tuner2_report(void)
{
}
#endif

int main(void)
{
	struct hid8k_snapshot snap;
	bool heavy = IS_ENABLED(CONFIG_HID8K_CDC_HEAVY_AT_BOOT);
	uint32_t prev_cycles;
	int64_t prev_uptime_ms;
	uint32_t fill_seq = 0U;
	uint64_t fill_owed_x1000 = 0U;
	int64_t now;
	int64_t last_tick;
	int64_t next_line;
	int64_t next_hist;
	int64_t next_mirror;
	bool led_on = false;
	int ret;

	printk("hid8k: 8 kHz HID proof, USB %04x:%04x. The default 1209:0001 is the pid.codes "
	       "test PID: not unique, for private bench testing only, never for a product.\n",
	       CONFIG_HID8K_USB_VID, CONFIG_HID8K_USB_PID);

	ret = hid8k_init(hid8k_usbd_context());
	if (ret != 0) {
		printk("hid8k: HID init failed (%d)\n", ret);
		return ret;
	}

	ret = cdc_console_init(on_command);
	if (ret != 0) {
		printk("hid8k: CDC console init failed (%d)\n", ret);
		return ret;
	}

	phy_tuner2_apply();

	ret = hid8k_usb_init();
	if (ret != 0) {
		printk("hid8k: USB init failed (%d)\n", ret);
		return ret;
	}
	phy_tuner2_report();

	ret = hid8k_usb_enable();
	if (ret != 0) {
		printk("hid8k: USB enable failed (%d)\n", ret);
		return ret;
	}

	if (led.port != NULL && gpio_is_ready_dt(&led)) {
		(void)gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	}

	hid8k_set_cdc_heavy(heavy);
	printk("hid8k: USB enabled; stats on the CDC ACM console every %d ms\n",
	       CONFIG_HID8K_LOG_PERIOD_MS);

	hid8k_take_snapshot(&snap, false);
	prev_cycles = snap.cycles;
	prev_uptime_ms = snap.uptime_ms;
	now = k_uptime_get();
	last_tick = now;
	next_line = now + CONFIG_HID8K_LOG_PERIOD_MS;
	next_hist = now + (int64_t)CONFIG_HID8K_HIST_PERIOD_S * 1000;
	next_mirror = now;

	while (true) {
		atomic_val_t want_heavy;
		bool reset;

		k_sleep(K_MSEC(heavy ? HEAVY_TICK_MS : MIN(CONFIG_HID8K_LOG_PERIOD_MS, IDLE_TICK_MS)));
		now = k_uptime_get();

		want_heavy = atomic_set(&req_heavy, -1);
		if (want_heavy >= 0 && (want_heavy != 0) != heavy) {
			heavy = want_heavy != 0;
			hid8k_set_cdc_heavy(heavy);
			fill_owed_x1000 = 0U;
			cdc_puts(heavy ? "hid8k mode=heavy\r\n" : "hid8k mode=normal\r\n");
		}

		if (atomic_set(&req_help, 0) != 0) {
			print_help();
		}

		if (atomic_set(&req_unknown, 0) != 0) {
			cdc_puts("hid8k unknown command (try: help)\r\n");
		}

		if (heavy) {
			fill_owed_x1000 += (uint64_t)CONFIG_HID8K_CDC_HEAVY_BPS * (uint64_t)(now - last_tick);
			write_filler((uint32_t)(fill_owed_x1000 / 1000U), &fill_seq);
			fill_owed_x1000 %= (uint64_t)FILL_LINE_LEN * 1000U;
		}
		last_tick = now;

		reset = atomic_set(&req_reset, 0) != 0;

		if (now >= next_line || reset) {
			const bool hist_now = atomic_set(&req_hist, 0) != 0 ||
					      (CONFIG_HID8K_HIST_PERIOD_S > 0 && now >= next_hist);
			uint32_t window_cycles;
			bool cyc_ok;
			int len;

			/* Print the histogram before a reset clears it. */
			hid8k_take_snapshot(&snap, reset);
			window_cycles = snap.cycles - prev_cycles;
			cyc_ok = cycles_consistent(window_cycles, snap.uptime_ms - prev_uptime_ms,
						   hid8k_cpu_hz());
			prev_cycles = snap.cycles;
			prev_uptime_ms = snap.uptime_ms;
			hid8k_cycle_counter_keepalive();
			/* Backstop: restart the HID stream if a refused submit left nothing queued. */
			hid8k_kick();

			len = format_stats(&snap, window_cycles, heavy, cyc_ok);
			if (len > 0) {
				cdc_puts(line);
				if (IS_ENABLED(CONFIG_HID8K_MIRROR_TO_CONSOLE) && now >= next_mirror) {
					printk("%s", line);
					next_mirror = now + MIRROR_MIN_MS;
				}
			}

			if (hist_now) {
				print_hist(&snap);
				next_hist = now + (int64_t)CONFIG_HID8K_HIST_PERIOD_S * 1000;
			}

			if (reset) {
				cdc_puts("hid8k stats reset\r\n");
			}

			if (led.port != NULL && snap.win.completions > 0U) {
				led_on = !led_on;
				(void)gpio_pin_set_dt(&led, led_on ? 1 : 0);
			}

			next_line += CONFIG_HID8K_LOG_PERIOD_MS;
			if (next_line <= now) {
				next_line = now + CONFIG_HID8K_LOG_PERIOD_MS;
			}
		}
	}

	return 0;
}
