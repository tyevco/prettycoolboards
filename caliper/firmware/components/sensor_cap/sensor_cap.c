/*
 * sensor_cap: EXPERIMENTAL capacitive scale driver.
 *
 * One burst: start ADC1 continuous sampling of CAP_RX at ~80.6 kS/s, then step the 8 TX phases
 * (dedicated-GPIO bundle) every 2 ADC sample periods (24.8 us; 8 steps = one ~5.04 kHz cycle):
 * CAP_K cycles rotating forward, then CAP_K cycles in reverse. The demodulator (cap_demod.c)
 * takes one window from each half; the reverse/forward phase difference is twice the position
 * phase, independent of the unknown start delay between the ADC and the drive loop.
 *
 * Timing (2026-11-07 review): the demodulator assumes exactly SPC = 16 ADC samples per drive
 * cycle. The ESP32-S3 ADC digital controller cannot sample at an arbitrary rate: it runs at
 * APB (80 MHz) / 16 / 2 / interval with an integer interval (esp_adc, hal/adc_hal.c), so the
 * 80000 S/s asked for before became interval 31 = 80645 S/s. Driving the phases from a fixed
 * 25.000 us CPU-cycle clock against that gave 16.13 samples per cycle (0.8 % off): the windows
 * drifted against the drive by ~2 samples per half and the result carried a phase error. The
 * step period is now SPS real ADC sample periods (read back from the clock tree the driver
 * uses), counted in cycles of the CPU clock actually running.
 *
 * Other burst hygiene (same review): the driver's pool is emptied before and after each burst
 * (adc_continuous_stop() leaves unread frames in it, which shifted the next burst's sample
 * index); a burst whose drive started late (preempted after the ADC start) is discarded instead
 * of clamping the delay estimate; CONFIG_ADC_CONTINUOUS_ISR_IRAM_SAFE is set in sdkconfig.defaults
 * so a flash write on core 0 (log, NVS) cannot stall the ADC ISR long enough for the 5-frame DMA
 * ring to overwrite unread samples.
 */
#include "sensor_cap.h"

#include <string.h>

#include "board_pins.h"
#include "cap_demod.h"
#include "driver/dedic_gpio.h"
#include "driver/gpio.h"
#include "esp_adc/adc_continuous.h"
#include "esp_check.h"
#include "esp_clk_tree.h"
#include "esp_cpu.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "soc/soc_caps.h"

static const char *TAG = "cap";

/* ADC digital controller clock: APB / ADC_CLKM_DIV (ADC_LL_CLKM_DIV_NUM_DEFAULT + 1 = 16 on the S3)
 * / 2 / interval. ADC_INTERVAL 31 = 80645.16 S/s (the S3 limit is 83333). FS_REQ_HZ is the rate
 * requested from the driver, which computes interval = APB / 16 / 2 / FS_REQ_HZ = 31 (truncated). */
#define ADC_CLKM_DIV 16
#define ADC_INTERVAL 31
#define FS_REQ_HZ    (80000000 / ADC_CLKM_DIV / 2 / ADC_INTERVAL) /* 80645 */
#define D_EST_MAX    64 /* samples between the ADC start and the drive start; more = preempted */
#define SPS          2     /* samples per drive step */
#define SPC          (SPS * CAP_PHASES) /* samples per drive cycle = 16 */
#define CAP_K        16    /* cycles per direction */
#define MARGIN_CYC   2     /* cycles skipped at each end of each half (start/switch uncertainty) */
#define WIN_SAMPLES  ((CAP_K - 2 * MARGIN_CYC) * SPC)
#define TAIL_STEPS   (2 * CAP_PHASES)
#define MAX_SAMPLES  (2 * CAP_K * SPC + 128)
#define MIN_AMP_LSB  CAP_MIN_AMP_LSB
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
/* the ADC sample period as the hardware runs it: s_fs_den / s_fs_num seconds */
static uint32_t s_fs_num = 80000000u;                       /* APB Hz */
static uint32_t s_fs_den = ADC_CLKM_DIV * 2 * ADC_INTERVAL; /* APB cycles per sample */
/* bring-up diagnostics (sensor_cap_diag): written by the cap task, copied by the CLI */
static cap_diag_t s_diag;
static portMUX_TYPE s_diag_mux = portMUX_INITIALIZER_UNLOCKED;

static void diag_put(esp_err_t err, bool late, const cap_reading_t *r, cap_iq_t f, cap_iq_t rv, float mean)
{
    taskENTER_CRITICAL(&s_diag_mux);
    s_diag.running = true;
    s_diag.bursts++;
    if (err != ESP_OK) {
        s_diag.errors++;
    } else if (late) {
        s_diag.late++;
    } else {
        s_diag.fwd = f;
        s_diag.rev = rv;
        s_diag.mean_lsb = mean;
        s_diag.amp_fwd = r->amp_fwd;
        s_diag.amp_rev = r->amp_rev;
        s_diag.frac = r->frac;
        s_diag.valid += r->valid;
    }
    taskEXIT_CRITICAL(&s_diag_mux);
}

void sensor_cap_diag(cap_diag_t *out)
{
    taskENTER_CRITICAL(&s_diag_mux);
    *out = s_diag;
    taskEXIT_CRITICAL(&s_diag_mux);
}

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

    /* the same clock source and precision the driver uses in adc_continuous_config() */
    uint32_t apb = 0;
    if (esp_clk_tree_src_get_freq_hz(SOC_MOD_CLK_APB, ESP_CLK_TREE_SRC_FREQ_PRECISION_CACHED, &apb) == ESP_OK &&
        apb > 0) {
        uint32_t interval = apb / ADC_CLKM_DIV / 2 / FS_REQ_HZ;
        s_fs_num = apb;
        s_fs_den = ADC_CLKM_DIV * 2u * (interval ? interval : 1u);
    }
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
        .sample_freq_hz = FS_REQ_HZ,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    ESP_RETURN_ON_ERROR(adc_continuous_config(s_adc, &ccfg), TAG, "adc config");
#if CONFIG_PM_ENABLE
    ESP_RETURN_ON_ERROR(esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "cap", &s_pm), TAG, "pm lock");
#endif
    cap_unwrap_init(&s_unwrap);
    ESP_LOGW(TAG, "capacitive scale enabled (EXPERIMENTAL), ADC %lu S/s", (unsigned long)(s_fs_num / s_fs_den));
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

/* Steps the phases with cycle-counter timing, interrupts masked on this core. One step = SPS ADC
 * sample periods, in cycles of the CPU clock actually running (the PM lock holds it at max). */
static int64_t drive_burst(void)
{
    const uint64_t cpu_hz = (uint64_t)esp_rom_get_cpu_ticks_per_us() * 1000000u;
    const uint32_t step_cycles = (uint32_t)((cpu_hz * SPS * s_fs_den + s_fs_num / 2) / s_fs_num);
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
    /* Anything still in the driver's pool belongs to an earlier burst (adc_continuous_stop() does
     * not empty it); left there it would shift every sample index of this burst. */
    adc_continuous_flush_pool(s_adc);
    bool late = false;
    cap_iq_t f = {0}, r = {0};
    float mean = 0.0f;
    esp_err_t err = adc_continuous_start(s_adc);
    /* start() enables the controller as its last step: the first sample follows closely */
    int64_t t_adc = esp_timer_get_time();
    if (err != ESP_OK) {
        goto done;
    }
    int64_t t_drive = drive_burst();
    /* samples taken before the drive started */
    int64_t d_est = (t_drive - t_adc) * (int64_t)s_fs_num / ((int64_t)s_fs_den * 1000000);
    late = d_est < 0 || d_est > D_EST_MAX;
    size_t want = (late ? 0 : (size_t)d_est) + 2 * CAP_K * SPC + SPC;
    size_t n = late ? 0 : collect(want);
    adc_continuous_stop(s_adc);
    adc_continuous_flush_pool(s_adc);
    if (late) {
        /* preempted between the ADC start and the drive (a higher-priority task on this core):
         * the windows would not line up with the drive. The old code clamped the estimate and
         * demodulated the wrong samples without noticing; discard the burst instead. */
        out->bursts = ++s_bursts;
        goto done; /* valid = false, err = ESP_OK */
    }
    if (n < want) {
        err = ESP_ERR_TIMEOUT;
        goto done;
    }
    size_t f0 = (size_t)d_est + MARGIN_CYC * SPC;
    size_t r0 = (size_t)d_est + (size_t)CAP_K * SPC + MARGIN_CYC * SPC;
    f = cap_demod_iq(&s_samples[f0], WIN_SAMPLES, (float)SPC, f0);
    r = cap_demod_iq(&s_samples[r0], WIN_SAMPLES, (float)SPC, r0);
    uint32_t sum = 0;
    for (size_t i = 0; i < WIN_SAMPLES; i++) {
        sum += s_samples[f0 + i];
    }
    mean = (float)sum / (float)WIN_SAMPLES; /* the DC level at the ADC: CAP_VREF through the filter */
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
    diag_put(err, late, out, f, r, mean);
    return err;
}
