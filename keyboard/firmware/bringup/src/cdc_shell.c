/*
 * A second shell instance on the CDC ACM UART, beside the board's USART1 shell. The shell UART backend's
 * transport API is public (include/zephyr/shell/shell_uart.h, Zephyr v4.5.0), so a second instance is the same
 * SHELL_UART_DEFINE / SHELL_DEFINE pair that subsys/shell/backends/shell_uart.c uses for the chosen one.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>
#include <zephyr/shell/shell_uart.h>

#include "cdc_shell.h"

SHELL_UART_DEFINE(tb_cdc_transport);
SHELL_DEFINE(tb_cdc_sh, "tb:cdc> ", &tb_cdc_transport, CONFIG_SHELL_BACKEND_SERIAL_LOG_MESSAGE_QUEUE_SIZE,
	     CONFIG_SHELL_BACKEND_SERIAL_LOG_MESSAGE_QUEUE_TIMEOUT, SHELL_FLAG_OLF_CRLF);

static bool started;

int tb_cdc_shell_start(void)
{
	const struct device *dev = DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));
	static const struct shell_backend_config_flags flags = SHELL_DEFAULT_BACKEND_CONFIG_FLAGS;
	int err;

	if (!device_is_ready(dev)) {
		return -ENODEV;
	}
	err = shell_init(&tb_cdc_sh, dev, flags, true, LOG_LEVEL_INF);
	if (err == 0) {
		started = true;
	}
	return err;
}

const struct shell *tb_cdc_shell(void)
{
	return started ? &tb_cdc_sh : NULL;
}
