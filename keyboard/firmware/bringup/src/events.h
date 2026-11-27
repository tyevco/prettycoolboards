/*
 * Asynchronous events (PROTOCOL.md "Events"): a ring the board service writes without blocking, and a printer
 * thread that copies new entries to both shells. A shell that is busy or not read may miss a line; the ring
 * keeps the last CONFIG_BRINGUP_EVENT_RING, and "tb ev" replays them by sequence number.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_EVENTS_H_
#define TB_EVENTS_H_

#include <stdint.h>
#include <zephyr/shell/shell.h>

/* Post "@tb ev seq=<n> t_ms=<t> <text>"; text is "kind=<kind> key=value ...". Never blocks. */
void tb_ev(const char *fmt, ...) __printf_like(1, 2);
/* Replay events with seq >= since on one shell. Returns how many. */
int tb_ev_dump(const struct shell *sh, uint32_t since);
uint32_t tb_ev_next_seq(void);
void tb_ev_start(void);

#endif /* TB_EVENTS_H_ */
