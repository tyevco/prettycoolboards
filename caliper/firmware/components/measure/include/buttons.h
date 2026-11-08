/*
 * Button debouncing and gesture detection (short press, long press, two-button combos).
 * Portable C: fed with the raw pressed-mask and a millisecond clock.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BTN_ZERO (1u << 0)
#define BTN_HOLD (1u << 1) /* HOLD/SEND */
#define BTN_MODE (1u << 2)

#define BTN_DEBOUNCE_MS 20
#define BTN_LONG_MS     800
#define BTN_COMBO_MS    1500

typedef enum {
    BTN_EV_NONE = 0,
    BTN_EV_SHORT, /* one button, released before BTN_LONG_MS */
    BTN_EV_LONG,  /* one button held BTN_LONG_MS (fires while still held) */
    BTN_EV_COMBO, /* two or more buttons held together BTN_COMBO_MS (fires while held) */
} btn_ev_type_t;

typedef struct {
    btn_ev_type_t type;
    uint8_t mask;
} btn_event_t;

typedef struct {
    uint8_t raw;          /* last raw sample */
    uint32_t raw_since;   /* when raw last changed */
    uint8_t stable;       /* debounced state */
    uint8_t session_mask; /* union of the buttons pressed since the first press */
    uint32_t session_t;   /* when the current mask was reached */
    bool fired;           /* a LONG/COMBO already fired in this session */
} btn_sm_t;

void btn_init(btn_sm_t *b);
/* Call every 5..20 ms. Returns at most one event per call. */
btn_event_t btn_update(btn_sm_t *b, uint8_t raw_pressed, uint32_t now_ms);

#ifdef __cplusplus
}
#endif
