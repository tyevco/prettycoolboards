/* Button gestures -> commands / navigation (see the table in ui.h). */
#include <stdio.h>

#include "caliper_core.h"
#include "esp_app_desc.h"
#include "ui.h"

static void menu_select(bool long_press)
{
    switch (ui_menu_selected()) {
    case UI_MENU_UNIT: core_command(CORE_CMD_TOGGLE_UNIT, 0); break;
    case UI_MENU_PROFILE: core_command(CORE_CMD_NEXT_PROFILE, 0); break;
    case UI_MENU_AUTOHOLD: core_command(CORE_CMD_AUTOHOLD_TOGGLE, 0); break;
    case UI_MENU_WIFI: core_command(CORE_CMD_WIFI, CAL_WIFI_TOGGLE); break;
    case UI_MENU_PROVISION: core_command(CORE_CMD_WIFI, CAL_WIFI_PROVISION); break;
    case UI_MENU_STATS_RESET: core_command(CORE_CMD_STATS_RESET, 0); break;
    case UI_MENU_LOG_CLEAR:
        if (long_press) {
            core_command(CORE_CMD_LOG_CLEAR, 0);
        } else {
            ui_toast("Hold HOLD to clear the log");
        }
        break;
    case UI_MENU_SLEEP: core_command(CORE_CMD_SLEEP, 0); break;
    default: {
        char b[48];
        cal_status_t st;
        core_get_status(&st);
        snprintf(b, sizeof(b), "fw %.20s  %.15s", esp_app_get_description()->version, st.ip);
        ui_toast(b);
        break;
    }
    }
}

void ui_handle_button(btn_event_t ev)
{
    if (ev.type == BTN_EV_NONE) {
        return;
    }
    core_activity();
    /* Without a working display the buttons still measure: everything acts as on the main screen
     * (no screen changes, no menu). With one, a press that cannot get the LVGL lock in 100 ms is
     * dropped rather than acted on against a half-drawn screen. */
    bool locked = ui_lock();
    if (!locked && ui_ready()) {
        return;
    }
    ui_screen_t scr = locked ? ui_screens_current() : UI_SCR_MAIN;

    if (ev.type == BTN_EV_COMBO) {
        if (ev.mask == (BTN_ZERO | BTN_MODE)) {
            core_command(CORE_CMD_WIFI, CAL_WIFI_PROVISION);
        } else if (ev.mask == (BTN_ZERO | BTN_HOLD)) {
            core_command(CORE_CMD_STATS_RESET, 0);
        } else if (ev.mask == (BTN_HOLD | BTN_MODE)) {
            core_command(CORE_CMD_SLEEP, 0);
        }
    } else if (scr == UI_SCR_MENU) {
        if (ev.type == BTN_EV_SHORT && ev.mask == BTN_ZERO) {
            ui_menu_move(-1);
        } else if (ev.type == BTN_EV_SHORT && ev.mask == BTN_MODE) {
            ui_menu_move(+1);
        } else if (ev.mask == BTN_HOLD) {
            menu_select(ev.type == BTN_EV_LONG);
        } else if (ev.type == BTN_EV_LONG && ev.mask == BTN_MODE) {
            ui_screens_show(UI_SCR_MAIN);
        }
    } else {
        switch (ev.mask) {
        case BTN_ZERO:
            core_command(ev.type == BTN_EV_SHORT ? CORE_CMD_ZERO : CORE_CMD_TOGGLE_UNIT, 0);
            break;
        case BTN_HOLD:
            core_command(ev.type == BTN_EV_SHORT ? CORE_CMD_HOLD_TOGGLE : CORE_CMD_SEND, 0);
            break;
        case BTN_MODE:
            if (ev.type == BTN_EV_SHORT) {
                if (locked) {
                    ui_screens_show((ui_screen_t)(scr + 1));
                }
            } else {
                core_command(CORE_CMD_NEXT_PROFILE, 0);
            }
            break;
        default:
            break;
        }
    }
    if (locked) {
        ui_unlock();
    }
}
