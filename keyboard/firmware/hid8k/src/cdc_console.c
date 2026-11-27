/*
 * hid8k: the CDC ACM console. Lines from the stats thread go through a ring buffer to the
 * CDC ACM UART's interrupt-driven API; host input is read a line at a time and handed to
 * the command callback.
 *
 * In Zephyr's device_next CDC ACM the "interrupt" callback runs in a work queue (the system
 * work queue unless CONFIG_USBD_CDC_ACM_WORKQUEUE), and uart_fifo_fill()/uart_fifo_read()
 * belong in that callback (with the dedicated work queue the class enforces it,
 * check_wq_ctx() in usbd_cdc_acm.c). That work queue is
 * cooperative, like the USB stack's own threads, so the callback copies at most
 * CONFIG_HID8K_CDC_CHUNK bytes per run and then returns; the class resubmits its work item
 * while TX stays enabled and has space, and the work queue yields between items.
 *
 * The ring has one producer (cdc_console_write(), called only from the stats thread) and one
 * consumer (the callback). Zephyr's ring buffer orders its index updates with acquire and
 * release barriers for that case (include/zephyr/sys/ring_buffer.h), so no lock is taken.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/ring_buffer.h>
#include <zephyr/sys/util.h>

#include "cdc_console.h"

LOG_MODULE_REGISTER(cdc_console, LOG_LEVEL_INF);

#define CMD_MAX 32U

static const struct device *const cdc_dev = DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));

RING_BUF_DECLARE(tx_ring, CONFIG_HID8K_CDC_RING_SIZE);

static atomic_t queued;
static atomic_t dropped;

static cdc_console_cmd_cb_t cmd_cb;
static char cmd_line[CMD_MAX + 1U];
static size_t cmd_len;
static bool cmd_overflow;

static void rx_byte(const uint8_t c)
{
	if (c == '\r' || c == '\n') {
		if (cmd_len > 0U && !cmd_overflow && cmd_cb != NULL) {
			cmd_line[cmd_len] = '\0';
			cmd_cb(cmd_line);
		}
		cmd_len = 0U;
		cmd_overflow = false;
		return;
	}

	if (cmd_len < CMD_MAX) {
		cmd_line[cmd_len++] = (char)c;
	} else {
		/* Not a command (echoed output, a modem probe): ignore the whole line. */
		cmd_overflow = true;
	}
}

static void rx_drain(const struct device *dev)
{
	uint8_t rx[16];
	int n;

	n = uart_fifo_read(dev, rx, sizeof(rx));
	for (int i = 0; i < n; i++) {
		rx_byte(rx[i]);
	}
}

/* Returns false when this run's byte budget is spent or the class took nothing. */
static bool tx_fill(const struct device *dev, const int space, uint32_t *const budget)
{
	uint8_t *data;
	uint32_t n;
	int sent;

	if (*budget == 0U) {
		/* Leave TX enabled: the class runs the callback again after the queue yields. */
		return false;
	}

	n = ring_buf_get_ptr(&tx_ring, &data, 0);
	n = MIN(n, MIN((uint32_t)space, *budget));
	if (n == 0U) {
		uart_irq_tx_disable(dev);
		return true;
	}

	sent = uart_fifo_fill(dev, data, (int)n);
	if (sent <= 0) {
		return false;
	}

	ring_buf_consume(&tx_ring, (size_t)sent);
	*budget -= MIN(*budget, (uint32_t)sent);

	return true;
}

static void cdc_irq_handler(const struct device *dev, void *user_data)
{
	uint32_t budget = CONFIG_HID8K_CDC_CHUNK;
	int space;

	ARG_UNUSED(user_data);

	while (true) {
		uart_irq_update(dev);
		if (uart_irq_is_pending(dev) <= 0) {
			break;
		}

		if (uart_irq_rx_ready(dev) > 0) {
			rx_drain(dev);
		}

		space = uart_irq_tx_ready(dev);
		if (space > 0 && !tx_fill(dev, space, &budget)) {
			break;
		}
	}
}

size_t cdc_console_write(const char *const data, const size_t len)
{
	uint32_t put;

	/*
	 * All or nothing: a line cut off by a full ring would run into the next one and spoil
	 * both for the host's line counter. This is the only producer, so the space can only
	 * grow between this check and the put.
	 */
	if (len == 0U || ring_buf_space_get(&tx_ring) < len) {
		(void)atomic_add(&dropped, (atomic_val_t)len);
		return 0U;
	}

	put = ring_buf_put(&tx_ring, (const uint8_t *)data, (uint32_t)len);

	(void)atomic_add(&queued, (atomic_val_t)put);
	if (put < len) {
		(void)atomic_add(&dropped, (atomic_val_t)(len - put));
	}

	if (put > 0U) {
		uart_irq_tx_enable(cdc_dev);
	}

	return put;
}

uint32_t cdc_console_queued(void)
{
	return (uint32_t)atomic_get(&queued);
}

uint32_t cdc_console_dropped(void)
{
	return (uint32_t)atomic_get(&dropped);
}

uint32_t cdc_console_pending(void)
{
	return ring_buf_size_get(&tx_ring);
}

int cdc_console_init(const cdc_console_cmd_cb_t cb)
{
	int ret;

	if (!device_is_ready(cdc_dev)) {
		LOG_ERR("CDC ACM device not ready");
		return -ENODEV;
	}

	cmd_cb = cb;

	ret = uart_irq_callback_user_data_set(cdc_dev, cdc_irq_handler, NULL);
	if (ret != 0) {
		LOG_ERR("uart_irq_callback_user_data_set failed: %d", ret);
		return ret;
	}

	uart_irq_rx_enable(cdc_dev);

	return 0;
}
