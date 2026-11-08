/* Backlight (LEDC), piezo (LEDC), RGB status LED (led_strip over RMT). */
#include <stdbool.h>

#include "board_pins.h"
#include "driver/ledc.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "led_strip.h"
#include "power.h"

static const char *TAG = "outputs";

#define BL_TIMER   LEDC_TIMER_0
#define BL_CHANNEL LEDC_CHANNEL_0
#define BL_FREQ_HZ 20000 /* above hearing */
#define BL_RES     LEDC_TIMER_10_BIT
#define BZ_TIMER   LEDC_TIMER_1
#define BZ_CHANNEL LEDC_CHANNEL_1
#define BZ_FREQ_HZ 4000  /* typical piezo resonance (TVP against the chosen part) */
#define BZ_RES     LEDC_TIMER_10_BIT

static led_strip_handle_t s_led;
static esp_timer_handle_t s_beep_timer;
static bool s_ready;

static void beep_off(void *arg)
{
    (void)arg;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, BZ_CHANNEL, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, BZ_CHANNEL);
}

esp_err_t power_outputs_init(void)
{
    ledc_timer_config_t bt = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = BL_RES,
        .timer_num = BL_TIMER,
        .freq_hz = BL_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&bt), TAG, "bl timer");
    ledc_channel_config_t bc = {
        .gpio_num = PIN_LCD_BL,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = BL_CHANNEL,
        .timer_sel = BL_TIMER,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_RETURN_ON_ERROR(ledc_channel_config(&bc), TAG, "bl channel");

    ledc_timer_config_t zt = bt;
    zt.timer_num = BZ_TIMER;
    zt.freq_hz = BZ_FREQ_HZ;
    zt.duty_resolution = BZ_RES;
    ESP_RETURN_ON_ERROR(ledc_timer_config(&zt), TAG, "bz timer");
    ledc_channel_config_t zc = bc;
    zc.gpio_num = PIN_BUZZ;
    zc.channel = BZ_CHANNEL;
    zc.timer_sel = BZ_TIMER;
    ESP_RETURN_ON_ERROR(ledc_channel_config(&zc), TAG, "bz channel");

    esp_timer_create_args_t ta = {.callback = beep_off, .name = "beep"};
    ESP_RETURN_ON_ERROR(esp_timer_create(&ta, &s_beep_timer), TAG, "beep timer");

    led_strip_config_t sc = {
        .strip_gpio_num = PIN_RGB_DIN,
        .max_leds = 1,
        .led_model = LED_MODEL_WS2812,
    };
    led_strip_rmt_config_t rc = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
    };
    if (led_strip_new_rmt_device(&sc, &rc, &s_led) != ESP_OK) {
        ESP_LOGW(TAG, "RGB LED init failed");
        s_led = NULL;
    } else {
        led_strip_clear(s_led);
    }
    s_ready = true;
    return ESP_OK;
}

void power_backlight(uint8_t pct)
{
    if (!s_ready) {
        return;
    }
    if (pct > 100) {
        pct = 100;
    }
    uint32_t max = (1u << BL_RES) - 1u;
    /* perceptual curve: duty ~ pct^2 */
    uint32_t duty = (uint32_t)pct * pct * max / 10000u;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, BL_CHANNEL, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, BL_CHANNEL);
}

void power_beep(uint32_t ms)
{
    if (!s_ready || ms == 0) {
        return;
    }
    ledc_set_duty(LEDC_LOW_SPEED_MODE, BZ_CHANNEL, 1u << (BZ_RES - 1)); /* 50 % */
    ledc_update_duty(LEDC_LOW_SPEED_MODE, BZ_CHANNEL);
    esp_timer_stop(s_beep_timer);
    esp_timer_start_once(s_beep_timer, (uint64_t)ms * 1000u);
}

void power_led(uint8_t r, uint8_t g, uint8_t b)
{
    if (!s_led) {
        return;
    }
    if (r == 0 && g == 0 && b == 0) {
        led_strip_clear(s_led);
        return;
    }
    led_strip_set_pixel(s_led, 0, r, g, b);
    led_strip_refresh(s_led);
}
