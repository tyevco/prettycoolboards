/*
 * The second shell, on the CDC ACM function (the first is the board's zephyr,shell-uart, USART1).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_CDC_SHELL_H_
#define TB_CDC_SHELL_H_

#include <errno.h>
#include <zephyr/shell/shell.h>

#if defined(CONFIG_BRINGUP_USB)
int tb_cdc_shell_start(void);
/* NULL until started. */
const struct shell *tb_cdc_shell(void);
#else
static inline int tb_cdc_shell_start(void)
{
	return -ENOTSUP;
}
static inline const struct shell *tb_cdc_shell(void)
{
	return NULL;
}
#endif

#endif /* TB_CDC_SHELL_H_ */
