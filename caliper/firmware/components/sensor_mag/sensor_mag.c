/* sensor_mag: AS5311 over PCNT (quadrature) + bit-banged SSI. */
#include "sensor_mag.h"

#include <string.h>

#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/pulse_cnt.h"
#include "esp_attr.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "measure.h"
#include "sdkconfig.h"

static const char *TAG = "mag";

#define PCNT_LIMIT       30000 /* hardware counter is 16-bit; the driver accumulates overflows */
/* SSI vs count disagreement tolerated before a correction, in SSI LSB (4 per count): the
 * incremental outputs have 2 counts (8 LSB) of hysteresis on a direction change (datasheet §7.2),
 * plus a few LSB of SSI jitter. */
#define SLIP_TOL_LSB     14
#define IDX_TOL_LSB      16
#define UNLOCK_SETTLE_MS 2     /* A/B leave their power-up "all high" state after the first CSn low */
#define BAD_FRAMES_LIMIT 3
#define POWER_UP_MS      20    /* AS5311 power-up to first valid frame (TVP) */
#define OCF_WAIT_MS      100

/* SSI position assumed to increase with the PCNT count as configured below (TVP: if bring-up
 * shows the opposite, flip this; the slip residual then stays near 0 while moving). */
#define SSI_SIGN 1

#if CONFIG_CALIPER_MAG_DIR_INVERT
#define USER_DIR -1
#else
#define USER_DIR 1
#endif

#define RTC_MAGIC 0xA5311A55u
typedef struct {
    uint32_t magic;
    int64_t count;
    uint16_t ssi;
} mag_rtc_t;
RTC_DATA_ATTR static mag_rtc_t s_rtc;

static pcnt_unit_handle_t s_unit;
static int64_t s_base; /* internal count = s_base + pcnt */
static as5311_slip_t s_slip;
static bool s_powered;
static uint8_t s_bad_frames;
static uint32_t s_slips;
static volatile int s_idx_pcnt;
static volatile bool s_idx_new;
static int32_t s_idx_ref = -1;

/* ---- SSI ------------------------------------------------------------------------------------ */

/* AS5311 rev 1.12 Table 10 / Figure 6: CLK idles HIGH (it must be high at the CSn falling edge,
 * else the frame carries the field magnitude), tCLKFE >= 500 ns from CSn low to the first CLK
 * falling edge (which latches the data), each rising edge shifts out one bit (valid <= 413 ns
 * later), TCLK/2 >= 500 ns, fCLK <= 1 MHz, tCSn >= 500 ns high between frames. Here: 1 us
 * half periods (~500 kHz) and the bit is sampled 1 us after each rising edge. */
static uint32_t ssi_read_raw(void)
{
    gpio_set_level(PIN_MAG_CLK, 1);
    gpio_set_level(PIN_MAG_CSN, 1);
    esp_rom_delay_us(1); /* tCSn */
    gpio_set_level(PIN_MAG_CSN, 0);
    esp_rom_delay_us(1); /* tCLKFE */
    uint32_t v = 0;
    for (int i = 0; i < AS5311_FRAME_BITS; i++) {
        gpio_set_level(PIN_MAG_CLK, 0);
        esp_rom_delay_us(1);
        gpio_set_level(PIN_MAG_CLK, 1); /* data changes after the rising edge */
        esp_rom_delay_us(1);
        v = (v << 1) | (uint32_t)(gpio_get_level(PIN_MAG_DO) & 1);
    }
    gpio_set_level(PIN_MAG_CSN, 1);
    return v;
}

static bool ssi_read(as5311_frame_t *f)
{
    as5311_decode(ssi_read_raw(), f);
    return as5311_frame_valid(f);
}

/* ---- index ---------------------------------------------------------------------------------- */

static void IRAM_ATTR idx_isr(void *arg)
{
    (void)arg;
    int c = 0;
    if (pcnt_unit_get_count(s_unit, &c) == ESP_OK) {
        s_idx_pcnt = c;
        s_idx_new = true;
    }
}

/* ---- power ---------------------------------------------------------------------------------- */

esp_err_t sensor_mag_power(bool on)
{
    if (on == s_powered) {
        return ESP_OK;
    }
    if (on) {
        gpio_hold_dis(PIN_SNS_PWR_EN);
        gpio_set_level(PIN_SNS_PWR_EN, 1);
        gpio_set_level(PIN_MAG_CSN, 1);
        gpio_set_level(PIN_MAG_CLK, 1);
        vTaskDelay(pdMS_TO_TICKS(POWER_UP_MS));
    } else {
        /* don't back-power the unpowered AS5311 through its inputs */
        gpio_set_level(PIN_MAG_CSN, 0);
        gpio_set_level(PIN_MAG_CLK, 0);
        gpio_set_level(PIN_SNS_PWR_EN, 0);
    }
    s_powered = on;
    return ESP_OK;
}

/* Waits for OCF (offset compensation finished) and returns the first valid frame. */
static bool wait_first_frame(as5311_frame_t *f)
{
    for (int t = 0; t < OCF_WAIT_MS; t += 2) {
        if (ssi_read(f)) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return false;
}

/* ---- init ----------------------------------------------------------------------------------- */

static esp_err_t pcnt_setup(void)
{
    pcnt_unit_config_t ucfg = {
        .low_limit = -PCNT_LIMIT,
        .high_limit = PCNT_LIMIT,
        .flags.accum_count = 1,
    };
    ESP_RETURN_ON_ERROR(pcnt_new_unit(&ucfg, &s_unit), TAG, "pcnt unit");
    pcnt_glitch_filter_config_t filt = {.max_glitch_ns = 100};
    ESP_RETURN_ON_ERROR(pcnt_unit_set_glitch_filter(s_unit, &filt), TAG, "glitch filter");

    pcnt_chan_config_t a_cfg = {.edge_gpio_num = PIN_MAG_A, .level_gpio_num = PIN_MAG_B};
    pcnt_chan_config_t b_cfg = {.edge_gpio_num = PIN_MAG_B, .level_gpio_num = PIN_MAG_A};
    pcnt_channel_handle_t ca, cb;
    ESP_RETURN_ON_ERROR(pcnt_new_channel(s_unit, &a_cfg, &ca), TAG, "chan a");
    ESP_RETURN_ON_ERROR(pcnt_new_channel(s_unit, &b_cfg, &cb), TAG, "chan b");
    /* 4x decoding: both edges of both channels, direction from the other channel's level */
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(ca, PCNT_CHANNEL_EDGE_ACTION_DECREASE,
                                                 PCNT_CHANNEL_EDGE_ACTION_INCREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(ca, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                                  PCNT_CHANNEL_LEVEL_ACTION_INVERSE));
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(cb, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                                 PCNT_CHANNEL_EDGE_ACTION_DECREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(cb, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                                  PCNT_CHANNEL_LEVEL_ACTION_INVERSE));
    /* the accumulation needs the limits as watch points */
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(s_unit, PCNT_LIMIT));
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(s_unit, -PCNT_LIMIT));
    ESP_ERROR_CHECK(pcnt_unit_enable(s_unit));
    ESP_ERROR_CHECK(pcnt_unit_clear_count(s_unit));
    ESP_ERROR_CHECK(pcnt_unit_start(s_unit));
    return ESP_OK;
}

esp_err_t sensor_mag_init(void)
{
    gpio_config_t out = {
        .pin_bit_mask = (1ULL << PIN_SNS_PWR_EN) | (1ULL << PIN_MAG_CLK) | (1ULL << PIN_MAG_CSN),
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&out), TAG, "gpio out");
    gpio_config_t in = {
        .pin_bit_mask = (1ULL << PIN_MAG_DO) | (1ULL << PIN_MAG_INC_N) | (1ULL << PIN_MAG_DEC_N),
        .mode = GPIO_MODE_INPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&in), TAG, "gpio in");
    gpio_config_t idx = {
        .pin_bit_mask = 1ULL << PIN_MAG_IDX,
        .mode = GPIO_MODE_INPUT,
        .intr_type = GPIO_INTR_POSEDGE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&idx), TAG, "gpio idx");

    s_powered = false;
    ESP_RETURN_ON_ERROR(sensor_mag_power(true), TAG, "power");
    ESP_RETURN_ON_ERROR(pcnt_setup(), TAG, "pcnt");

    esp_err_t err = gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    ESP_RETURN_ON_ERROR(gpio_isr_handler_add(PIN_MAG_IDX, idx_isr, NULL), TAG, "idx isr");

    as5311_slip_init(&s_slip, SSI_SIGN);
    as5311_frame_t f;
    bool got = wait_first_frame(&f);
    if (got) {
        /* CSn was high at power-up, so A/B/Index sat high until the first CSn low pulse
         * (datasheet §7.1.1): let them settle into the real quadrature state (that transition
         * may produce a stray count), then take the reference frame and count together. */
        vTaskDelay(pdMS_TO_TICKS(UNLOCK_SETTLE_MS));
        got = ssi_read(&f) || wait_first_frame(&f);
    }
    if (!got) {
        ESP_LOGE(TAG, "no valid SSI frame (sensor missing, unpowered or OCF never set)");
        s_base = 0;
        s_bad_frames = BAD_FRAMES_LIMIT;
        s_rtc.magic = 0;
        return ESP_OK; /* keep counting; readings are flagged SENSOR_ERR */
    }
    int c = 0;
    pcnt_unit_get_count(s_unit, &c);
    if (esp_reset_reason() == ESP_RST_DEEPSLEEP && s_rtc.magic == RTC_MAGIC) {
        int64_t cnt = as5311_recover_count(s_rtc.count, s_rtc.ssi, f.pos, SSI_SIGN);
        s_base = cnt - c;
        ESP_LOGI(TAG, "recovered count %lld after sleep (moved %ld SSI LSB while off)", (long long)cnt,
                 (long)as5311_wrap_diff(f.pos, s_rtc.ssi));
    } else {
        s_base = -c; /* cold boot: origin here */
    }
    s_rtc.magic = 0; /* only valid for the next wake */
    as5311_slip_lock(&s_slip, s_base + c, f.pos);
    ESP_LOGI(TAG, "AS5311 ok, pos %u, field %d", f.pos, (int)as5311_field(&f));
    return ESP_OK;
}

/* ---- read ----------------------------------------------------------------------------------- */

esp_err_t sensor_mag_read(mag_reading_t *out, bool do_ssi)
{
    memset(out, 0, sizeof(*out));
    if (!s_unit) {
        return ESP_ERR_INVALID_STATE;
    }
    int c1 = 0;
    pcnt_unit_get_count(s_unit, &c1);

    if (do_ssi && s_powered) {
        as5311_frame_t f;
        bool valid = ssi_read(&f);
        int c2 = 0;
        pcnt_unit_get_count(s_unit, &c2);
        if (valid) {
            s_bad_frames = 0;
            out->ssi_valid = true;
            out->ssi_pos = f.pos;
            out->field = as5311_field(&f);
            if (!s_slip.locked) {
                as5311_slip_lock(&s_slip, s_base + c1, f.pos);
            } else if (c1 == c2) { /* not moving during the frame: the comparison is meaningful */
                int32_t r = as5311_slip_residual(&s_slip, s_base + c1, f.pos);
                out->slip = r;
                if (r > SLIP_TOL_LSB || r < -SLIP_TOL_LSB) {
                    /* the SSI position is absolute within the pole: trust it */
                    int32_t k = as5311_slip_correction(&s_slip, r);
                    s_base += k;
                    s_slips++;
                    ESP_LOGW(TAG, "count slip of %ld counts (%ld LSB) corrected", (long)k, (long)r);
                }
            }
        } else if (s_bad_frames < 255) {
            s_bad_frames++;
        }
    }

    if (s_idx_new) {
        s_idx_new = false;
        int32_t ph = (int32_t)as5311_count_phase(s_base + s_idx_pcnt, 1);
        if (s_idx_ref < 0) {
            s_idx_ref = ph;
        } else {
            int32_t d = as5311_wrap_diff((uint16_t)ph, (uint16_t)s_idx_ref);
            if (d > IDX_TOL_LSB || d < -IDX_TOL_LSB) {
                ESP_LOGW(TAG, "index at phase %ld, expected %ld", (long)ph, (long)s_idx_ref);
            }
        }
    }

    int64_t internal = s_base + c1;
    out->count = USER_DIR * internal;
    out->raw_nm = meas_counts_to_nm(out->count);
    out->slips = s_slips;
    out->ok = s_powered && s_bad_frames < BAD_FRAMES_LIMIT && out->field != AS5311_FIELD_BAD;
    return ESP_OK;
}

void sensor_mag_prepare_sleep(void)
{
    as5311_frame_t f;
    int c = 0;
    if (s_unit && s_powered && ssi_read(&f) && pcnt_unit_get_count(s_unit, &c) == ESP_OK) {
        s_rtc.count = s_base + c;
        s_rtc.ssi = f.pos;
        s_rtc.magic = RTC_MAGIC;
    } else {
        s_rtc.magic = 0;
    }
    sensor_mag_power(false);
    gpio_hold_en(PIN_SNS_PWR_EN);
}
