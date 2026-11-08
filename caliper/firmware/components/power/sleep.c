/* Deep sleep: ext1 wake on IMU_INT1 (pickup), the three buttons and CHG_INT_N (USB plugged). */
#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/rtc_io.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "power.h"

static const char *TAG = "sleep";

bool power_imu_clear(void);

#define BTN_MASK ((1ULL << PIN_BTN_ZERO_N) | (1ULL << PIN_BTN_HOLD_N) | (1ULL << PIN_BTN_MODE_N))

/* pads held low through deep sleep, released by power_release_holds() after wake */
static const gpio_num_t s_held[] = {PIN_LCD_BL,  PIN_BUZZ,     PIN_SNS_PWR_EN, PIN_MAG_CLK, PIN_MAG_CSN, PIN_LCD_SCK,
                                    PIN_LCD_MOSI, PIN_LCD_CS_N, PIN_LCD_DC,     PIN_LCD_RST_N, PIN_RGB_DIN};

void power_release_holds(void)
{
    gpio_deep_sleep_hold_dis();
    for (size_t i = 0; i < sizeof(s_held) / sizeof(s_held[0]); i++) {
        gpio_hold_dis(s_held[i]);
    }
}

static bool any_button_down(void)
{
    return !gpio_get_level(PIN_BTN_ZERO_N) || !gpio_get_level(PIN_BTN_HOLD_N) || !gpio_get_level(PIN_BTN_MODE_N);
}

void power_deep_sleep(void)
{
    power_backlight(0);
    power_led(0, 0, 0);
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0);

    /* a button still held would wake us at once */
    for (int i = 0; i < 300 && any_button_down(); i++) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    uint64_t mask = BTN_MASK | (1ULL << PIN_CHG_INT_N);
    if (power_imu_clear()) {
        mask |= 1ULL << PIN_IMU_INT1; /* LIS2DW12 INT1 is active low, latched (power.c) */
    }
    /* every wake line has an external pull-up (buttons 100 k, CHG_INT_N 10 k) or is push-pull
     * (IMU INT1), so no RTC pull-ups and RTC_PERIPH can power down */
    const gpio_num_t wake[] = {PIN_BTN_ZERO_N, PIN_BTN_HOLD_N, PIN_BTN_MODE_N, PIN_CHG_INT_N, PIN_IMU_INT1};
    for (size_t i = 0; i < sizeof(wake) / sizeof(wake[0]); i++) {
        rtc_gpio_pullup_dis(wake[i]);
        rtc_gpio_pulldown_dis(wake[i]);
    }
    esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);

    /* keep the backlight gate, the piezo gate (GPIO45 strap: must stay low), the rail switch
     * and every line into the switched rails low while asleep */
    gpio_set_direction(PIN_LCD_BL, GPIO_MODE_OUTPUT);
    gpio_set_level(PIN_LCD_BL, 0);
    gpio_set_direction(PIN_BUZZ, GPIO_MODE_OUTPUT);
    gpio_set_level(PIN_BUZZ, 0);
    for (size_t i = 0; i < sizeof(s_held) / sizeof(s_held[0]); i++) {
        gpio_hold_en(s_held[i]);
    }
    gpio_deep_sleep_hold_en();

    ESP_LOGI(TAG, "deep sleep, wake mask 0x%llx", (unsigned long long)mask);
    vTaskDelay(pdMS_TO_TICKS(20)); /* let the log drain */
    esp_deep_sleep_start();
}

void power_ui_lines_low(void)
{
    /* +3V3_UI (ST7789 VDD, WS2812) goes off with SNS_PWR_EN: don't back-power them through the
     * ESD diodes of their inputs (SPEC §3). Takes the pins from SPI / RMT. */
    const gpio_num_t lines[] = {PIN_LCD_SCK, PIN_LCD_MOSI, PIN_LCD_CS_N, PIN_LCD_DC, PIN_LCD_RST_N, PIN_RGB_DIN};
    for (size_t i = 0; i < sizeof(lines) / sizeof(lines[0]); i++) {
        gpio_reset_pin(lines[i]);
        gpio_set_direction(lines[i], GPIO_MODE_OUTPUT);
        gpio_set_level(lines[i], 0);
    }
}

const char *power_wake_cause(void)
{
    switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_EXT1: {
        uint64_t m = esp_sleep_get_ext1_wakeup_status();
        if (m & (1ULL << PIN_IMU_INT1)) return "pickup";
        if (m & (1ULL << PIN_CHG_INT_N)) return "usb";
        if (m & BTN_MASK) return "button";
        return "ext1";
    }
    case ESP_SLEEP_WAKEUP_UNDEFINED:
        return "power-on";
    default:
        return "other";
    }
}
