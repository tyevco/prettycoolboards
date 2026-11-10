/*
 * PrettyCool Caliper rev A firmware: wiring and tasks.
 *
 *   task      core prio  rate     job
 *   sensor    1    10    100 Hz   AS5311 count + SSI (fine position) -> core_sample()
 *   cap       1    4     25 Hz    EXPERIMENTAL capacitive burst -> shared value
 *   buttons   0    7     100 Hz   debounce + gestures -> ui_handle_button()
 *   app       0    3     10 Hz    BLE notifications; 1 Hz power poll, USB poll, dim/auto-off
 *   bus       0    6     events   commands and events (caliper_core event loop)
 *   imu       0    5     50 Hz    LSM6DSO gyro + accelerometer -> orientation (power/imu.c)
 *   + NimBLE host, LVGL (esp_lvgl_port), TinyUSB, httpd, mqtt, ble_wrk, push, cli
 */
#include <string.h>

#include "ble.h"
#include "board_pins.h"
#include "buttons.h"
#include "caliper_core.h"
#include "caliper_gatt.h"
#include "caliper_usb.h"
#include "caliper_wifi.h"
#include "driver/gpio.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_pm.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "pin_plan.h"
#include "power.h"
#include "sdkconfig.h"
#include "sensor_cap.h"
#include "sensor_mag.h"
#include "store.h"
#include "ui.h"

static const char *TAG = "app";

#define BACKLIGHT_ON_PCT  70
#define BACKLIGHT_DIM_PCT 10
#define DIM_AFTER_MS      30000
#define LOW_BATTERY_PCT   3
/* Wi-Fi off below the start floor minus this, without USB (wifi.c, docs/firmware.md §12.6) */
#define WIFI_STOP_HYST_MV 100
#define CAP_FAIL_LIMIT    50 /* consecutive failed bursts before the cap sensor is shut down */

static esp_pm_lock_handle_t s_awake_lock;

/* the capacitive value, handed from the cap task to the sensor task */
static portMUX_TYPE s_cap_mux = portMUX_INITIALIZER_UNLOCKED;
static int64_t s_cap_raw_nm;
static bool s_cap_ok;

static void cap_put(bool ok, int64_t nm)
{
    taskENTER_CRITICAL(&s_cap_mux);
    s_cap_ok = ok;
    if (ok) {
        s_cap_raw_nm = nm;
    }
    taskEXIT_CRITICAL(&s_cap_mux);
}

static bool cap_get(int64_t *nm)
{
    taskENTER_CRITICAL(&s_cap_mux);
    bool ok = s_cap_ok;
    *nm = s_cap_raw_nm;
    taskEXIT_CRITICAL(&s_cap_mux);
    return ok;
}

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* ---- sensor ------------------------------------------------------------------------------- */

static void sensor_task(void *arg)
{
    (void)arg;
    TickType_t last = xTaskGetTickCount();
    bool have_slips = false;
    uint32_t slips = 0;
    for (;;) {
        mag_reading_t m;
        /* SSI on every sample (~40 us): the count is refined to 488 nm only with a fresh frame */
        bool ok = sensor_mag_read(&m, true) == ESP_OK && m.ok;
        if (ok) {
            if (have_slips && m.slips != slips) {
                core_mag_slip(); /* the count was re-aligned: the reading stepped, drop a running capture */
            }
            have_slips = true;
            slips = m.slips;
        }
        int64_t cap_nm;
        bool cap_ok = cap_get(&cap_nm);
        core_sample(m.raw_nm, ok, cap_nm, cap_ok, now_ms());
        vTaskDelayUntil(&last, pdMS_TO_TICKS(10));
    }
}

static void cap_task(void *arg)
{
    (void)arg;
    int fails = 0;
    for (;;) {
        cap_reading_t c;
        if (sensor_cap_measure(&c) == ESP_OK && c.valid) {
            cap_put(true, c.pos_nm);
            fails = 0;
        } else {
            cap_put(false, 0);
            if (++fails >= CAP_FAIL_LIMIT) {
                ESP_LOGW(TAG, "capacitive sensor gave no valid burst %d times: stopped", CAP_FAIL_LIMIT);
                sensor_cap_deinit();
                vTaskDelete(NULL);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(40));
    }
}

/* ---- buttons ------------------------------------------------------------------------------ */

static void buttons_task(void *arg)
{
    (void)arg;
    /* inputs, no pull: 100 k external pull-ups + 100 nF (10 ms RC); the pin plan's RUN state */
    pin_plan_apply(PP_MODE_RUN, pin_plan_init_mask(PP_INIT_BUTTONS), 0);
    btn_sm_t sm;
    btn_init(&sm);
    uint8_t stable = 0;
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        uint8_t raw = 0;
        if (!gpio_get_level(PIN_BTN_ZERO_N)) raw |= BTN_ZERO;
        if (!gpio_get_level(PIN_BTN_HOLD_N)) raw |= BTN_HOLD;
        if (!gpio_get_level(PIN_BTN_MODE_N)) raw |= BTN_MODE;
        uint32_t t = now_ms();
        btn_event_t ev = btn_update(&sm, raw, t);
        if (sm.stable != stable) {
            /* pressing the housing lifts the slider pads (calcs §3): keep it out of a capture */
            stable = sm.stable;
            core_button_edge(stable != 0, t);
        }
        if (ev.type != BTN_EV_NONE) {
            ui_handle_button(ev);
        }
        vTaskDelayUntil(&last, pdMS_TO_TICKS(10));
    }
}

/* ---- sleep -------------------------------------------------------------------------------- */

static void enter_sleep(void)
{
    ESP_LOGI(TAG, "going to sleep");
    core_command(CORE_CMD_WIFI, CAL_WIFI_OFF);
    vTaskDelay(pdMS_TO_TICKS(50));
    ui_sleep();
    power_ui_lines_low();         /* before +3V3_UI goes off */
    sensor_cap_idle();
    sensor_mag_prepare_sleep();   /* reads the pole position, then SNS_PWR_EN low: +3V3_SNS and +3V3_UI off */
    power_deep_sleep();
}

static void on_sleep(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    (void)data;
    enter_sleep();
}

static void on_beep(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    power_beep(*(const uint32_t *)data);
}

static esp_timer_handle_t s_led_timer;

static void led_off(void *arg)
{
    (void)arg;
    power_led(0, 0, 0);
}

static void on_recorded(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    const logrec_t *r = (const logrec_t *)data;
    if (r->flags & CALIPER_FLAG_TOL_FAIL) {
        power_led(40, 0, 0);
    } else if (r->flags & CALIPER_FLAG_TOL_PASS) {
        power_led(0, 40, 0);
    } else {
        power_led(20, 20, 20);
    }
    esp_timer_stop(s_led_timer);
    esp_timer_start_once(s_led_timer, 150 * 1000);
}

/* ---- app: BLE notifications, power, auto-off --------------------------------------------- */

static void app_task(void *arg)
{
    (void)arg;
    uint32_t tick = 0;
    uint8_t backlight = BACKLIGHT_ON_PCT;
    for (;;) {
        ble_tick();
        if (tick++ % 10 == 0) {
            power_status_t ps;
            power_poll(&ps);
            core_set_power(ps.soc_pct, ps.vcell_mv, ps.charging, ps.vbus);
            caliper_usb_poll();

            uint32_t idle = core_idle_ms();
            uint8_t want = idle > DIM_AFTER_MS ? BACKLIGHT_DIM_PCT : BACKLIGHT_ON_PCT;
            if (want != backlight) {
                backlight = want;
                power_backlight(backlight);
            }
            settings_t s;
            core_get_settings(&s);
            bool keep_awake = caliper_usb_host() || caliper_wifi_active();
            if (s.auto_off_s && !keep_awake && idle > s.auto_off_s * 1000u) {
                ESP_LOGI(TAG, "auto-off after %lu s idle", (unsigned long)(idle / 1000));
                enter_sleep();
            }
            if (ps.gauge_ok && ps.vcell_mv > 0 && !ps.vbus && caliper_wifi_active() &&
                ps.vcell_mv < CONFIG_CALIPER_WIFI_MIN_MV - WIFI_STOP_HYST_MV) {
                ESP_LOGW(TAG, "battery %u mV: Wi-Fi off", (unsigned)ps.vcell_mv);
                uint32_t off = CAL_WIFI_OFF;
                bus_post(CAL_EVT_WIFI, &off, sizeof(off));
                char m[32] = "Battery low: Wi-Fi off";
                bus_post(CAL_EVT_TOAST, m, sizeof(m));
            }
            if (ps.gauge_ok && ps.vcell_mv > 0 && ps.soc_pct < LOW_BATTERY_PCT && !ps.vbus) {
                char m[32] = "Battery empty";
                bus_post(CAL_EVT_TOAST, m, sizeof(m));
                vTaskDelay(pdMS_TO_TICKS(1500));
                enter_sleep();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/* ---- startup ------------------------------------------------------------------------------ */

static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

static void init_pm(void)
{
#if CONFIG_PM_ENABLE
    esp_pm_config_t pm = {
        .max_freq_mhz = CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,
        .min_freq_mhz = 40,
        .light_sleep_enable = true,
    };
    ESP_ERROR_CHECK(esp_pm_configure(&pm));
    /* While awake the AS5311 counter must never stop: light sleep would gate the PCNT clock.
     * Automatic light sleep therefore only happens if a future standby state drops this lock. */
    ESP_ERROR_CHECK(esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "awake", &s_awake_lock));
    esp_pm_lock_acquire(s_awake_lock);
#endif
}

void app_main(void)
{
    ESP_LOGI(TAG, "PrettyCool Caliper fw %s, board rev %s (pins %s), wake: %s", esp_app_get_description()->version,
             BOARD_REV, BOARD_PINS_HASH, power_wake_cause());
    /* the plain GPIOs nobody else owns (BOOT, FG_ALRT_N, CHG_INT_N, IMU_INT1/2) to their RUN state
     * (inputs, pulls off), written while the pads may still be held, then the holds released */
    pin_plan_apply(PP_MODE_RUN, pin_plan_init_mask(PP_INIT_BOARD), PP_APPLY_LEVEL);
    power_release_holds();
    init_nvs();
    init_pm();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    if (store_init() != ESP_OK) {
        ESP_LOGE(TAG, "storage unavailable: readings will not be saved");
    }
    ESP_ERROR_CHECK(core_init());
    bus_subscribe(CAL_EVT_SLEEP, on_sleep, NULL);
    bus_subscribe(CAL_EVT_BEEP, on_beep, NULL);
    bus_subscribe(CAL_EVT_RECORDED, on_recorded, NULL);
    esp_timer_create_args_t ta = {.callback = led_off, .name = "led"};
    esp_timer_create(&ta, &s_led_timer);

    power_init();
    /* SNS_PWR_EN also switches +3V3_UI (LCD VDD, RGB LED): the sensor driver turns the rails on
     * first, so the panel and the LED are powered before they are initialised */
    if (sensor_mag_init() != ESP_OK) {
        ESP_LOGE(TAG, "magnetic sensor init failed");
    }
    /* keep the zero across a deep sleep only if the AS5311 count was recovered */
    mag_origin_t origin = sensor_mag_origin();
    core_mag_origin(origin == MAG_ORIGIN_RECOVERED,
                    origin == MAG_ORIGIN_LOST ||
                        (origin == MAG_ORIGIN_NONE && esp_reset_reason() == ESP_RST_DEEPSLEEP));
    power_outputs_init();
    if (ui_init() != ESP_OK) {
        ESP_LOGE(TAG, "display init failed");
    }
    power_backlight(BACKLIGHT_ON_PCT);

    bool cap = false;
#if CONFIG_CALIPER_CAP_SENSOR
    cap = sensor_cap_init() == ESP_OK; /* on core 0: keeps the ADC DMA interrupt off core 1 */
    if (!cap) {
        ESP_LOGW(TAG, "capacitive sensor disabled (init failed)");
    }
#endif

    if (ble_init() != ESP_OK) {
        ESP_LOGE(TAG, "BLE init failed");
    }
    caliper_wifi_init();
    if (caliper_usb_init() != ESP_OK) {
        ESP_LOGE(TAG, "USB init failed");
    }

    /* the drivers set some pulls themselves (PCNT turns pull-ups on; GPIO45 / 46 keep their reset
     * pull-downs under LEDC / RMT; MTCK and U0TXD / U0RXD keep their reset pull-ups): the plan's RUN
     * pulls (none on every driver-owned pad but the USB pair, which is never touched) */
    pin_plan_apply_pulls(PP_MODE_RUN, pin_plan_init_mask(PP_INIT_DRIVER));

    xTaskCreatePinnedToCore(sensor_task, "sensor", 4096, NULL, 10, NULL, 1);
    if (cap) {
        xTaskCreatePinnedToCore(cap_task, "cap", 4096, NULL, 4, NULL, 1);
    }
    xTaskCreatePinnedToCore(buttons_task, "buttons", 4096, NULL, 7, NULL, 0);
    xTaskCreatePinnedToCore(app_task, "app", 4096, NULL, 3, NULL, 0);
    if (power_imu_start() != ESP_OK) {
        ESP_LOGW(TAG, "no IMU: no orientation, no pickup wake");
    }
    ESP_LOGI(TAG, "running");
}
