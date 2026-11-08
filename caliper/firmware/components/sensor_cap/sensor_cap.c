/*
 * sensor_cap: EXPERIMENTAL capacitive scale driver.
 *
 * One burst: start ADC1 continuous sampling of CAP_RX at 80 kS/s, then step the 8 TX phases
 * (dedicated-GPIO bundle) every 25 us (2 samples per step, 8 steps = one 5 kHz cycle):
 * CAP_K cycles rotating forward, then CAP_K cycles in reverse. The demodulator (cap_demod.c)
 * takes one window from each half; the reverse/forward phase difference is twice the position
 * phase, independent of the unknown start delay between the ADC and the drive loop.
 */
#include "sensor_cap.h"

#include <string.h>

#include "board_pins.h"
#include "cap_demod.h"
#include "driver/dedic_gpio.h"
#include "driver/gpio.h"
#include "esp_adc/adc_continuous.h"
#include "esp_check.h"
#include "esp_cpu.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "soc/soc_caps.h"

static const char *TAG = "cap";

#define FS_HZ        80000 /* ESP32-S3 ADC continuous limit is about 83.3 kS/s */
#define SPS          2     /* samples per drive step */
#define SPC          (SPS * CAP_PHASES) /* samples per drive cycle = 16 */
#define CAP_K        16    /* cycles per direction */
#define MARGIN_CYC   2     /* cycles skipped at each end of each half (start/switch uncertainty) */
#define WIN_SAMPLES  ((CAP_K - 2 * MARGIN_CYC) * SPC)
#define TAIL_STEPS   (2 * CAP_PHASES)
#define MAX_SAMPLES  (2 * CAP_K * SPC + 128)
#define MIN_AMP_LSB  8.0f
/* Direction of the capacitive reading relative to the magnetic one (TVP). */
#define CAP_SIGN     (-1)

static adc_continuous_handle_t s_adc;
static dedic_gpio_bundle_handle_t s_bundle;
static esp_pm_lock_handle_t s_pm;
static cap_unwrap_t s_unwrap;
static uint32_t s_bursts;
static uint8_t s_raw[MAX_SAMPLES * SOC_ADC_DIGI_RESULT_BYTES];
static uint16_t s_samples[MAX_SAMPLES];
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;

esp_err_t sensor_cap_init(void)
{
    const int pins[CAP_PHASES] = PIN_CAP_TX_LIST;
    gpio_config_t io = {.mode = GPIO_MODE_OUTPUT};
    for (int i = 0; i < CAP_PHASES; i++) {
        io.pin_bit_mask |= 1ULL << pins[i];
    }
    ESP_RETURN_ON_ERROR(gpio_config(&io), TAG, "tx gpio");
    dedic_gpio_bundle_config_t bcfg = {
        .gpio_array = pins,
        .array_size = CAP_PHASES,
        .flags = {.out_en = 1},
    };
    ESP_RETURN_ON_ERROR(dedic_gpio_new_bundle(&bcfg, &s_bundle), TAG, "bundle");
    dedic_gpio_bundle_write(s_bundle, 0xFF, 0);

    adc_continuous_handle_cfg_t hcfg = {
        .max_store_buf_size = sizeof(s_raw) + 1024,
        .conv_frame_size = 256,
    };
    ESP_RETURN_ON_ERROR(adc_continuous_new_handle(&hcfg, &s_adc), TAG, "adc handle");
    adc_digi_pattern_config_t patt = {
        .atten = ADC_ATTEN_DB_12,
        .channel = ADC_CHANNEL_0, /* GPIO1 = CAP_RX */
        .unit = ADC_UNIT_1,
        .bit_width = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    adc_continuous_config_t ccfg = {
        .pattern_num = 1,
        .adc_pattern = &patt,
        .sample_freq_hz = FS_HZ,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    ESP_RETURN_ON_ERROR(adc_continuous_config(s_adc, &ccfg), TAG, "adc config");
#if CONFIG_PM_ENABLE
    ESP_RETURN_ON_ERROR(esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "cap", &s_pm), TAG, "pm lock");
#endif
    cap_unwrap_init(&s_unwrap);
    ESP_LOGW(TAG, "capacitive scale enabled (EXPERIMENTAL)");
    return ESP_OK;
}

void sensor_cap_idle(void)
{
    if (s_bundle) {
        dedic_gpio_bundle_write(s_bundle, 0xFF, 0);
    }
}

void sensor_cap_deinit(void)
{
    sensor_cap_idle();
    if (s_adc) {
        adc_continuous_deinit(s_adc);
        s_adc = NULL;
    }
    if (s_bundle) {
        dedic_gpio_del_bundle(s_bundle);
        s_bundle = NULL;
    }
}

/* Steps the phases with cycle-counter timing, interrupts masked on this core. */
static int64_t drive_burst(void)
{
    const uint32_t step_cycles = (uint32_t)CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ * 1000000u / (FS_HZ / SPS);
    const int32_t fwd_steps = CAP_K * CAP_PHASES;
    const int32_t total = 2 * fwd_steps + TAIL_STEPS;
    int64_t t_start;
    taskENTER_CRITICAL(&s_mux);
    t_start = esp_timer_get_time();
    uint32_t t = esp_cpu_get_cycle_count();
    for (int32_t k = 0; k < total; k++) {
        dedic_gpio_bundle_write(s_bundle, 0xFF, cap_pattern(k < fwd_steps ? k : -k));
        t += step_cycles;
        while ((int32_t)(esp_cpu_get_cycle_count() - t) < 0) {
        }
    }
    taskEXIT_CRITICAL(&s_mux);
    dedic_gpio_bundle_write(s_bundle, 0xFF, 0);
    return t_start;
}

static size_t collect(size_t want)
{
    size_t n = 0;
    uint32_t got = 0;
    int64_t deadline = esp_timer_get_time() + 20000;
    while (n < want && esp_timer_get_time() < deadline) {
        if (adc_continuous_read(s_adc, s_raw, sizeof(s_raw), &got, 5) != ESP_OK) {
            continue;
        }
        for (uint32_t i = 0; i + SOC_ADC_DIGI_RESULT_BYTES <= got && n < MAX_SAMPLES;
             i += SOC_ADC_DIGI_RESULT_BYTES) {
            const adc_digi_output_data_t *p = (const adc_digi_output_data_t *)&s_raw[i];
            if (p->type2.channel == ADC_CHANNEL_0) {
                s_samples[n++] = (uint16_t)p->type2.data;
            }
        }
    }
    return n;
}

esp_err_t sensor_cap_measure(cap_reading_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!s_adc || !s_bundle) {
        return ESP_ERR_INVALID_STATE;
    }
#if CONFIG_PM_ENABLE
    esp_pm_lock_acquire(s_pm);
#endif
    int64_t t_adc = esp_timer_get_time();
    esp_err_t err = adc_continuous_start(s_adc);
    if (err != ESP_OK) {
        goto done;
    }
    int64_t t_drive = drive_burst();
    /* samples taken before the drive started */
    int64_t d_est = (t_drive - t_adc) * FS_HZ / 1000000;
    if (d_est < 0 || d_est > 64) {
        d_est = d_est < 0 ? 0 : 64;
    }
    size_t want = (size_t)d_est + 2 * CAP_K * SPC + SPC;
    size_t n = collect(want);
    adc_continuous_stop(s_adc);
    if (n < want) {
        err = ESP_ERR_TIMEOUT;
        goto done;
    }
    size_t f0 = (size_t)d_est + MARGIN_CYC * SPC;
    size_t r0 = (size_t)d_est + (size_t)CAP_K * SPC + MARGIN_CYC * SPC;
    cap_iq_t f = cap_demod_iq(&s_samples[f0], WIN_SAMPLES, (float)SPC, f0);
    cap_iq_t r = cap_demod_iq(&s_samples[r0], WIN_SAMPLES, (float)SPC, r0);
    out->amp_fwd = cap_iq_amplitude(f);
    out->amp_rev = cap_iq_amplitude(r);
    out->bursts = ++s_bursts;
    if (out->amp_fwd < MIN_AMP_LSB || out->amp_rev < MIN_AMP_LSB || out->amp_fwd > 2.0f * out->amp_rev ||
        out->amp_rev > 2.0f * out->amp_fwd) {
        out->valid = false; /* no coupling (no scale, open jumper) or a disturbed burst */
        goto done;
    }
    out->frac = cap_half_pitch_fraction(f, r);
    out->pos_nm = CAP_SIGN * cap_unwrap_update(&s_unwrap, out->frac);
    out->valid = true;
done:
#if CONFIG_PM_ENABLE
    esp_pm_lock_release(s_pm);
#endif
    return err;
}
