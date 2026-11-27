/*
 * Event ring and printer (see events.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/shell/shell_uart.h>
#include <zephyr/spinlock.h>

#include "cdc_shell.h"
#include "events.h"

#define EV_TEXT 120

struct ev {
	uint32_t seq;
	uint32_t t_ms;
	char text[EV_TEXT];
};

static struct ev ring[CONFIG_BRINGUP_EVENT_RING];
static uint32_t next_seq = 1;
static struct k_spinlock lock;
static K_SEM_DEFINE(ev_sem, 0, 1);

void tb_ev(const char *fmt, ...)
{
	struct ev e;
	va_list ap;
	k_spinlock_key_t key;

	va_start(ap, fmt);
	vsnprintf(e.text, sizeof(e.text), fmt, ap);
	va_end(ap);
	e.t_ms = k_uptime_get_32();
	key = k_spin_lock(&lock);
	e.seq = next_seq++;
	ring[e.seq % ARRAY_SIZE(ring)] = e;
	k_spin_unlock(&lock, key);
	k_sem_give(&ev_sem);
}

uint32_t tb_ev_next_seq(void)
{
	k_spinlock_key_t key = k_spin_lock(&lock);
	uint32_t s = next_seq;

	k_spin_unlock(&lock, key);
	return s;
}

static bool get(uint32_t seq, struct ev *out)
{
	k_spinlock_key_t key = k_spin_lock(&lock);
	bool ok = seq < next_seq && ring[seq % ARRAY_SIZE(ring)].seq == seq;

	if (ok) {
		*out = ring[seq % ARRAY_SIZE(ring)];
	}
	k_spin_unlock(&lock, key);
	return ok;
}

static void print_one(const struct shell *sh, const struct ev *e)
{
	if (sh != NULL) {
		shell_fprintf(sh, SHELL_NORMAL, "@tb ev seq=%u t_ms=%u %s\n", e->seq, e->t_ms, e->text);
	}
}

int tb_ev_dump(const struct shell *sh, uint32_t since)
{
	uint32_t end = tb_ev_next_seq();
	uint32_t first = end > ARRAY_SIZE(ring) ? end - ARRAY_SIZE(ring) : 1;
	struct ev e;
	int n = 0;

	for (uint32_t s = MAX(since, first); s < end; s++) {
		if (get(s, &e)) {
			print_one(sh, &e);
			n++;
		}
	}
	return n;
}

static void printer(void *a, void *b, void *c)
{
	uint32_t printed = 1;

	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	for (;;) {
		struct ev e;
		uint32_t end;

		k_sem_take(&ev_sem, K_FOREVER);
		end = tb_ev_next_seq();
		if (end > printed + ARRAY_SIZE(ring)) {
			printed = end - ARRAY_SIZE(ring);
		}
		for (; printed < end; printed++) {
			if (get(printed, &e)) {
				/* Either shell may block while its host does not read; this thread may wait. */
				print_one(shell_backend_uart_get_ptr(), &e);
				print_one(tb_cdc_shell(), &e);
			}
		}
	}
}

K_THREAD_DEFINE(tb_ev_printer, 2048, printer, NULL, NULL, NULL, K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);

void tb_ev_start(void)
{
	k_sem_give(&ev_sem);
}
