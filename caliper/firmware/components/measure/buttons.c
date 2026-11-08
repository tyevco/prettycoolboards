/* Button gestures. Portable C. */
#include "buttons.h"

#include <string.h>

static int popcount8(uint8_t v)
{
    int n = 0;
    while (v) {
        n += v & 1u;
        v >>= 1;
    }
    return n;
}

void btn_init(btn_sm_t *b)
{
    memset(b, 0, sizeof(*b));
}

btn_event_t btn_update(btn_sm_t *b, uint8_t raw, uint32_t now)
{
    btn_event_t ev = {BTN_EV_NONE, 0};

    if (raw != b->raw) {
        b->raw = raw;
        b->raw_since = now;
    }
    if (b->stable != b->raw && (uint32_t)(now - b->raw_since) >= BTN_DEBOUNCE_MS) {
        uint8_t prev = b->stable;
        b->stable = b->raw;
        if (prev == 0 && b->stable != 0) {
            b->session_mask = b->stable;
            b->session_t = now;
            b->fired = false;
        } else if (b->stable != 0) {
            if (b->stable & (uint8_t)~b->session_mask) {
                b->session_mask |= b->stable;
                b->session_t = now; /* combo timing restarts when a button joins */
            }
        } else {
            if (!b->fired && popcount8(b->session_mask) == 1) {
                ev.type = BTN_EV_SHORT;
                ev.mask = b->session_mask;
            }
            b->session_mask = 0;
            b->fired = false;
            return ev;
        }
    }

    if (b->stable != 0 && !b->fired) {
        int n = popcount8(b->session_mask);
        uint32_t held = now - b->session_t;
        if (n >= 2 && b->stable == b->session_mask && held >= BTN_COMBO_MS) {
            b->fired = true;
            ev.type = BTN_EV_COMBO;
            ev.mask = b->session_mask;
        } else if (n == 1 && held >= BTN_LONG_MS) {
            b->fired = true;
            ev.type = BTN_EV_LONG;
            ev.mask = b->session_mask;
        }
    }
    return ev;
}
