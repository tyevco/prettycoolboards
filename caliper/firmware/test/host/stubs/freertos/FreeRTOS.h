/* Host-test stub: single-threaded, so the store's mutex is a no-op. */
#pragma once

#include <stdint.h>

typedef uint32_t TickType_t;
#define portMAX_DELAY ((TickType_t)0xFFFFFFFFu)
#define pdTRUE 1
