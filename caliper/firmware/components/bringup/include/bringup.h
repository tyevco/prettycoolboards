/*
 * bringup: the guided first-board checks, as CLI commands in the normal image ("bu help" on the USB
 * console). Each check prints its numbers and ends with one line "PASS <name> ..." or
 * "FAIL <name> ...". The procedure around them (supplies, meter points, limits) is docs/bringup.md.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    void (*out)(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
    /* waits up to timeout_ms for the next line typed on the console; false on timeout */
    bool (*ask)(char *line, size_t len, uint32_t timeout_ms);
} bu_io_t;

/* args: the rest of the command line after "bu" (modified in place) */
void bringup_cmd(const bu_io_t *io, char *args);

#ifdef __cplusplus
}
#endif
