/*
 * ui: the 240 x 135 ST7789 IPS display (esp_lcd + esp_lvgl_port + LVGL 9) and the buttons.
 *
 * Screens (MODE cycles): MAIN (big reading, unit, capture tag + detail line, profile + tolerance
 * gauge, status icons) -> CHART (last 100 live values, 10 Hz) -> STATS -> MENU. A provisioning
 * screen is shown while the Wi-Fi setup AP runs.
 *
 * Buttons outside the menu:
 *   ZERO  short: zero (also clears / re-arms the capture)          long: mm <-> inch
 *   HOLD  short: hold on/off; in a capture mode: freeze a running capture, clear + re-arm a
 *                frozen one, else a hand hold                        long: SEND (record + type over BLE HID)
 *   MODE  short: next screen     long: next tolerance profile
 *   ZERO+MODE 1.5 s: Wi-Fi setup AP     ZERO+HOLD 1.5 s: reset stats
 *   HOLD+MODE 1.5 s: sleep now
 * In the menu: ZERO = up, MODE = down, HOLD = select (long HOLD for destructive items),
 * MODE long = leave the menu.
 */
#pragma once

#include "buttons.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t ui_init(void);
void ui_handle_button(btn_event_t ev); /* from the button task */
void ui_sleep(void);                   /* panel off before deep sleep */

/* internal (ui_*.c) */
typedef enum { UI_SCR_MAIN = 0, UI_SCR_CHART, UI_SCR_STATS, UI_SCR_MENU, UI_SCR_COUNT } ui_screen_t;
void ui_screens_create(void);
void ui_screens_show(ui_screen_t s);
ui_screen_t ui_screens_current(void);
void ui_menu_move(int delta);
int ui_menu_selected(void);
void ui_toast(const char *msg);
bool ui_ready(void);  /* the display and LVGL are up */
bool ui_lock(void);   /* false if not ready or busy for 100 ms */
void ui_unlock(void);

enum {
    UI_MENU_UNIT = 0,
    UI_MENU_PROFILE,
    UI_MENU_CAPTURE,   /* Capture: Off / Settle / Sweep (replaces Auto-hold) */
    UI_MENU_SWEEP_SEL, /* Sweep: Auto / Min / Max */
    UI_MENU_WIFI,
    UI_MENU_PROVISION,
    UI_MENU_STATS_RESET,
    UI_MENU_LOG_CLEAR,
    UI_MENU_SLEEP,
    UI_MENU_ABOUT,
    UI_MENU_COUNT
};

#ifdef __cplusplus
}
#endif
