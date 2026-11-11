/*
 * imu: the LSM6DSO 6-axis IMU (U60, I2C 0x6B, always-on +3V3). Two jobs:
 *
 *   awake   accelerometer + gyroscope at 52 Hz, both in low-power mode, read by a 50 Hz task and
 *           fused by components/measure/orient.c: roll / pitch from gravity, relative yaw, angular
 *           rate, "steady", gyro bias at rest (power_orient_get()). The same task polls the
 *           compass (compass.c) at 10 Hz and hands its samples to the same filter.
 *   asleep  gyroscope powered down, accelerometer in ultra-low-power mode at 12.5 Hz, the wake-up
 *           (slope) interrupt latched on INT1: the ext1 "pickup" wake of sleep.c.
 *
 * Sources: ST DS12140 Rev 3 (datasheet: register addresses, bits, scale factors; "DS §") and
 * AN5192 Rev 5 (application note: currents, start-up times, sequences; "AN §"). The currents are
 * typical values at VDD = 1.8 V; the datasheet gives none at the 3.3 V this board runs it from,
 * and nothing here has been measured.
 *
 * Why 52 Hz low-power and not the 0.55 mA high-performance mode: AN Table 9 gives 300 uA for the
 * accelerometer + gyroscope at 52 Hz in low-power mode against 550 uA in high-performance mode.
 * The gyroscope's drive dominates (265 uA already at 12.5 Hz), so going slower saves 20-35 uA and
 * costs integration accuracy on a quick flip (500 dps is 10 deg per sample at 52 Hz, 40 deg at
 * 12.5 Hz), while 104 Hz (normal mode, 350 uA) buys nothing for a hand tool whose motion lives below
 * 10 Hz. The price of low-power mode is noise: 75 mdps RMS (DS Table 2, RnRMS) instead of
 * 3.8 mdps/rtHz, which a display flip, a steady flag and a relative yaw do not notice.
 */
#include "imu.h"

#include "board_pins.h"
#include "compass.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "orient.h"
#include "power.h"

static const char *TAG = "imu";

/* ================================================================================================
 * AXIS MAPPING, chip -> board: THE one place.
 *
 * Board frame (orient.h): +x along the beam toward the USB end, +y toward the buttons / top edge,
 * +z out of the display face. U60 sits on the top side at 0 deg (hardware/design/SPEC.md §16), so
 * chip X = board +x, chip Y = board +y, chip Z = board +z: the identity.
 *
 * board = row * chip. A board revision that turns the part or moves it to the bottom side changes
 * these nine numbers and nothing else; power_imu_init() refuses a table that is not a rotation
 * (orient_mount_valid). The chip's own positive directions are a drawing in the datasheet (DS
 * §"Pin description", the axes figure): check them on the first board with "bu imu" (which face
 * reads +1 g) and "bu gyro turn" (the sign of each axis).
 * ============================================================================================== */
static const orient_mount_t s_mount = {{
    {1, 0, 0}, /* board +x (beam, toward USB)        = chip +X */
    {0, 1, 0}, /* board +y (toward the buttons)      = chip +Y */
    {0, 0, 1}, /* board +z (out of the display face) = chip +Z */
}};

/* ---- registers (DS §9) ---------------------------------------------------------------------- */
#define REG_WHO_AM_I    0x0F /* §9.11 */
#define REG_CTRL1_XL    0x10 /* §9.12: ODR_XL 7:4, FS_XL 3:2 */
#define REG_CTRL2_G     0x11 /* §9.13: ODR_G 7:4, FS_G 3:2, FS_125 1 */
#define REG_CTRL3_C     0x12 /* §9.14: BOOT 7, BDU 6, H_LACTIVE 5, PP_OD 4, SIM 3, IF_INC 2, SW_RESET 0 */
#define REG_CTRL5_C     0x14 /* §9.16: XL_ULP_EN 7 */
#define REG_CTRL6_C     0x15 /* §9.17: XL_HM_MODE 4 */
#define REG_CTRL7_G     0x16 /* §9.18: G_HM_MODE 7 */
#define REG_CTRL9_XL    0x18 /* §9.20: DEN_X/Y/Z 7:5 (default 1), I3C_disable 1 */
#define REG_ALL_INT_SRC 0x1A /* §9.22 */
#define REG_WAKE_UP_SRC 0x1B /* §9.23 */
#define REG_OUT_TEMP_L  0x20 /* §9.27; then OUTX_L_G 22h (§9.28) .. OUTZ_H_A 2Dh (§9.31 ff.) */
#define REG_TAP_CFG0    0x56 /* §9.41: INT_CLR_ON_READ 6, SLOPE_FDS 4, LIR 0 */
#define REG_TAP_CFG2    0x58 /* §9.43: INTERRUPTS_ENABLE 7 */
#define REG_WAKE_UP_THS 0x5B /* §9.46: WK_THS 5:0 */
#define REG_WAKE_UP_DUR 0x5C /* §9.47: WAKE_DUR 6:5, WAKE_THS_W 4 */
#define REG_MD1_CFG     0x5E /* §9.49: INT1_WU 5 */

#define WHO_AM_I_VAL 0x6C /* §9.11 */

#define CTRL3_SW_RESET 0x01
/* BDU (an output pair never mixes two samples), H_LACTIVE (interrupt pins active low), PP_OD = 0
 * (push-pull), IF_INC (the default: multi-byte reads). The ext1 wake of sleep.c is ANY_LOW with no
 * pull on IMU_INT1, so active low + push-pull is the contract with the hardware. */
#define CTRL3_VAL 0x64
/* I3C_disable: "recommended to set this bit to 1 during the initial device configuration phase,
 * when the I3C interface is not used" (DS §9.20). DEN_X/Y/Z stay at their default 1. */
#define CTRL9_VAL 0xE2
/* LIR (latched) with INT_CLR_ON_READ, which "must be set to 1 together with LIR" and clears the
 * latch at once when a source register is read (DS §9.41); SLOPE_FDS = 0: the slope filter. */
#define TAP_CFG0_VAL 0x41
#define TAP_CFG2_VAL 0x80 /* INTERRUPTS_ENABLE */
#define MD1_CFG_VAL  0x20 /* INT1_WU: the wake-up event on INT1, awake and asleep alike */
/* WAKE_THS_W = 0: 1 LSB = FS_XL / 2^6 = 31.25 mg at +-2 g (DS §9.47); 2 LSB = 62.5 mg, the same
 * register value the LIS2DW12 ran with. The slope the threshold is compared with is
 * [acc(tn) - acc(tn-1)] / 2 (AN §3.8.1), so equal sensitivity to the old part is an assumption
 * until a board has been picked up (TVP). No duration: one sample over the threshold wakes. */
#define WAKE_UP_THS_VAL 0x02
#define WAKE_UP_DUR_VAL 0x00

/* awake: both sensors at 52 Hz with high-performance mode off = low-power mode (DS §6.2.1 accel,
 * §6.3 gyro: low-power at 12.5 / 26 / 52 Hz when XL_HM_MODE / G_HM_MODE = 1) */
#define CTRL6_RUN    0x10 /* XL_HM_MODE = 1 */
#define CTRL7_RUN    0x80 /* G_HM_MODE = 1 */
#define CTRL1_XL_RUN 0x30 /* ODR_XL 0011 = 52 Hz, FS_XL 00 = +-2 g */
#define CTRL2_G_RUN  0x38 /* ODR_G 0011 = 52 Hz, FS_G 10 = +-1000 dps */
/* asleep: ultra-low-power, accelerometer only (DS §6.2.1): XL_ULP_EN = 1, XL_HM_MODE = 0, the
 * gyroscope in power-down; 5.5 uA at 12.5 Hz (AN Table 9) */
#define CTRL5_ULP      0x80 /* XL_ULP_EN */
#define CTRL6_ULP      0x00 /* XL_HM_MODE = 0 */
#define CTRL1_XL_SLEEP 0x10 /* ODR_XL 0001 = 12.5 Hz, +-2 g */

/* scale factors, DS Table 2 */
#define ACC_G_PER_LSB    0.000061f /* LA_So at +-2 g: 0.061 mg/LSB */
#define GYRO_DPS_PER_LSB 0.035f    /* G_So at +-1000 dps: 35 mdps/LSB */
#define GYRO_CLIP_LSB    32700     /* at the rail: the rate is unknown */
#define TEMP_LSB_PER_C   256.0f    /* DS §4.3 (temperature sensor): 256 LSB/degC, 0 = 25 degC */

#define I2C_HZ      400000
#define I2C_TIMEOUT 50 /* ms */

#define IMU_PERIOD_MS   20  /* 50 Hz poll of a 52 Hz output: every poll finds a new sample */
#define COMPASS_DIV     5   /* every 5th sample: the IIS2MDC's 10 Hz */
#define IMU_TASK_PRIO   5
#define IMU_TASK_CORE   0
/* gyroscope power-down -> low-power: 70 ms + discard 1 sample (AN Table 17); 52 Hz = 19.2 ms */
#define GYRO_START_MS   120
/* accelerometer power-down -> ULP 12.5 Hz, then two samples for the slope filter (80 ms each) */
#define SLEEP_SETTLE_MS 300

static i2c_master_dev_handle_t s_dev;
static bool s_ok;                /* answered with the right WHO_AM_I and took the configuration */
static SemaphoreHandle_t s_lock; /* the sampler against the sleep reconfiguration */
static bool s_run;               /* the sampler may read (under s_lock) */
static TaskHandle_t s_task;
static orient_t s_orient;        /* the sampler task's own */
static volatile bool s_zero_req;
static unsigned s_cmp_div;       /* the sampler task's own: samples since the last compass poll */
static uint32_t s_cmp_dt_us;     /* and the time since the last compass sample */

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static orient_out_t s_out;       /* under s_mux */
static power_imu_sample_t s_last;
static orient_compass_cal_t s_cmp_cal; /* under s_mux: waiting for the sampler while s_cmp_cal_req */
static volatile bool s_cmp_cal_req;

static esp_err_t wr8(uint8_t reg, uint8_t v)
{
    uint8_t b[2] = {reg, v};
    return i2c_master_transmit(s_dev, b, 2, I2C_TIMEOUT);
}

static esp_err_t rd(uint8_t reg, uint8_t *v, size_t n)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, v, n, I2C_TIMEOUT);
}

/* The interface and interrupt set-up, the same awake and asleep. INT1 is an input with a pull-down
 * until an interrupt is routed to it (DS §9.51: the pull-down is "connected only when no interrupts
 * are routed to the INT1 pin"), so between a reset and MD1_CFG the ESP32 reads IMU_INT1 LOW: the
 * wake-up stays routed for good, and power_imu_sleep_prepare() checks the level before sleeping. */
static esp_err_t write_common(void)
{
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL9_XL, CTRL9_VAL), TAG, "ctrl9");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL3_C, CTRL3_VAL), TAG, "ctrl3");
    ESP_RETURN_ON_ERROR(wr8(REG_TAP_CFG0, TAP_CFG0_VAL), TAG, "tap_cfg0");
    ESP_RETURN_ON_ERROR(wr8(REG_WAKE_UP_DUR, WAKE_UP_DUR_VAL), TAG, "wu dur");
    ESP_RETURN_ON_ERROR(wr8(REG_WAKE_UP_THS, WAKE_UP_THS_VAL), TAG, "wu ths");
    ESP_RETURN_ON_ERROR(wr8(REG_MD1_CFG, MD1_CFG_VAL), TAG, "md1");
    return wr8(REG_TAP_CFG2, TAP_CFG2_VAL);
}

static void clear_latch(void)
{
    uint8_t src;
    rd(REG_WAKE_UP_SRC, &src, 1);
    rd(REG_ALL_INT_SRC, &src, 1);
}

esp_err_t power_imu_init(i2c_master_bus_handle_t bus)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = I2C_ADDR_LSM6DSO,
        .scl_speed_hz = I2C_HZ,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &cfg, &s_dev), TAG, "add");
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) {
        return ESP_ERR_NO_MEM;
    }

    uint8_t who = 0;
    ESP_RETURN_ON_ERROR(rd(REG_WHO_AM_I, &who, 1), TAG, "who");
    if (who != WHO_AM_I_VAL) {
        ESP_LOGE(TAG, "LSM6DSO WHO_AM_I 0x%02x (0x%02x expected)", who, WHO_AM_I_VAL);
        return ESP_ERR_NOT_FOUND;
    }
    if (!orient_mount_valid(&s_mount)) {
        ESP_LOGE(TAG, "the axis mapping in imu.c is not a rotation");
        return ESP_ERR_INVALID_ARG;
    }

    /* The chip sits on the always-on rail: after a deep sleep it is still in the ULP wake-up set-up,
     * after a crash in whatever it had. Software reset to the defaults (AN §5.7: both sensors to
     * power-down, set SW_RESET, wait 50 us or poll until it reads 0), then configure. */
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL2_G, 0x00), TAG, "ctrl2 pd");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL1_XL, 0x00), TAG, "ctrl1 pd");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL3_C, CTRL3_SW_RESET), TAG, "reset");
    uint8_t c3 = CTRL3_SW_RESET;
    for (int i = 0; i < 10 && (c3 & CTRL3_SW_RESET); i++) {
        vTaskDelay(pdMS_TO_TICKS(2));
        if (rd(REG_CTRL3_C, &c3, 1) != ESP_OK) {
            c3 = CTRL3_SW_RESET;
        }
    }
    if (c3 & CTRL3_SW_RESET) {
        ESP_LOGE(TAG, "LSM6DSO software reset did not finish");
        return ESP_ERR_TIMEOUT;
    }

    ESP_RETURN_ON_ERROR(write_common(), TAG, "common");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL5_C, 0x00), TAG, "ctrl5");        /* ULP off (the default) */
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL6_C, CTRL6_RUN), TAG, "ctrl6");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL7_G, CTRL7_RUN), TAG, "ctrl7");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL1_XL, CTRL1_XL_RUN), TAG, "ctrl1");
    ESP_RETURN_ON_ERROR(wr8(REG_CTRL2_G, CTRL2_G_RUN), TAG, "ctrl2");
    clear_latch();
    s_ok = true;
    return ESP_OK;
}

esp_err_t power_imu_diag_read(uint8_t reg, uint8_t *buf, size_t n)
{
    return s_dev ? rd(reg, buf, n) : ESP_ERR_INVALID_STATE;
}

/* ---- the sampler ---------------------------------------------------------------------------- */

static int16_t le16(const uint8_t *b)
{
    return (int16_t)(uint16_t)(b[0] | (b[1] << 8));
}

static void sample_once(int64_t *t_prev)
{
    /* OUT_TEMP (20h-21h), gyro X/Y/Z (22h-27h), accelerometer X/Y/Z (28h-2Dh): one burst, 16-bit
     * two's complement, low byte first; BDU keeps each pair from one sample */
    uint8_t b[14];
    if (rd(REG_OUT_TEMP_L, b, sizeof(b)) != ESP_OK) {
        taskENTER_CRITICAL(&s_mux);
        s_last.errors++;
        taskEXIT_CRITICAL(&s_mux);
        return; /* the next good sample sees the gap in dt, which voids the yaw if it is long */
    }
    int64_t now = esp_timer_get_time();
    uint32_t dt_us = *t_prev ? (uint32_t)(now - *t_prev > 1000000 ? 1000000 : now - *t_prev) : IMU_PERIOD_MS * 1000u;
    *t_prev = now;

    bool clipped = false;
    orient_vec_t g_chip, a_chip;
    float *g[3] = {&g_chip.x, &g_chip.y, &g_chip.z}, *a[3] = {&a_chip.x, &a_chip.y, &a_chip.z};
    for (int i = 0; i < 3; i++) {
        int16_t gr = le16(&b[2 + 2 * i]);
        clipped |= gr >= GYRO_CLIP_LSB || gr <= -GYRO_CLIP_LSB;
        *g[i] = (float)gr * GYRO_DPS_PER_LSB;
        *a[i] = (float)le16(&b[8 + 2 * i]) * ACC_G_PER_LSB;
    }
    orient_vec_t gyro = orient_mount_apply(&s_mount, g_chip);
    orient_vec_t acc = orient_mount_apply(&s_mount, a_chip);

    if (s_zero_req) {
        s_zero_req = false;
        orient_zero_yaw(&s_orient);
    }
    if (s_cmp_cal_req) {
        taskENTER_CRITICAL(&s_mux);
        orient_compass_cal_t cal = s_cmp_cal;
        s_cmp_cal_req = false;
        taskEXIT_CRITICAL(&s_mux);
        orient_compass_set_cal(&s_orient, &cal);
    }
    orient_update(&s_orient, gyro, acc, dt_us, clipped);
    /* the compass, after the update: its heading is taken against the `up` of this sample. A poll
     * that finds no new sample waits for the next turn, and the sample after it carries the gap. */
    s_cmp_dt_us += s_cmp_dt_us < 1000000u ? dt_us : 0;
    if (++s_cmp_div >= COMPASS_DIV) {
        s_cmp_div = 0;
        orient_vec_t b_ut;
        if (power_compass_poll(&b_ut)) {
            orient_compass_update(&s_orient, b_ut, s_cmp_dt_us);
            s_cmp_dt_us = 0;
        }
    }
    orient_out_t out;
    orient_get(&s_orient, &out);

    taskENTER_CRITICAL(&s_mux);
    s_out = out;
    s_last.gyro_dps[0] = gyro.x;
    s_last.gyro_dps[1] = gyro.y;
    s_last.gyro_dps[2] = gyro.z;
    s_last.acc_g[0] = acc.x;
    s_last.acc_g[1] = acc.y;
    s_last.acc_g[2] = acc.z;
    s_last.temp_c = 25.0f + (float)le16(&b[0]) / TEMP_LSB_PER_C;
    s_last.gyro_clipped = clipped;
    s_last.samples++;
    taskEXIT_CRITICAL(&s_mux);
}

static void imu_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(GYRO_START_MS));
    int64_t t_prev = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(IMU_PERIOD_MS));
        xSemaphoreTake(s_lock, portMAX_DELAY);
        if (s_run) {
            sample_once(&t_prev);
        }
        xSemaphoreGive(s_lock);
    }
}

esp_err_t power_imu_start(void)
{
    if (!s_ok) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_task) {
        return ESP_OK;
    }
    orient_init(&s_orient, NULL);
    s_run = true;
    if (xTaskCreatePinnedToCore(imu_task, "imu", 4096, NULL, IMU_TASK_PRIO, &s_task, IMU_TASK_CORE) != pdPASS) {
        s_task = NULL;
        s_run = false;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

bool power_orient_get(orient_out_t *out)
{
    taskENTER_CRITICAL(&s_mux);
    *out = s_out;
    taskEXIT_CRITICAL(&s_mux);
    return out->valid;
}

void power_orient_zero_yaw(void)
{
    s_zero_req = true; /* taken by the sampler at its next sample */
}

void power_compass_cal_set(const orient_compass_cal_t *cal)
{
    taskENTER_CRITICAL(&s_mux);
    s_cmp_cal = cal ? *cal : (orient_compass_cal_t){0};
    s_cmp_cal_req = true; /* taken by the sampler at its next sample: after orient_init(), too */
    taskEXIT_CRITICAL(&s_mux);
}

bool power_imu_last(power_imu_sample_t *out)
{
    taskENTER_CRITICAL(&s_mux);
    *out = s_last;
    taskEXIT_CRITICAL(&s_mux);
    return out->samples > 0;
}

/* ---- sleep ---------------------------------------------------------------------------------- */

bool power_imu_sleep_prepare(void)
{
    if (!s_ok) {
        return false;
    }
    /* the sampler never reads again (deep sleep ends in a reset) */
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_run = false;
    xSemaphoreGive(s_lock);
    taskENTER_CRITICAL(&s_mux);
    s_out.valid = false;
    taskEXIT_CRITICAL(&s_mux);

    /* DS §6.2.1: ULP needs the gyroscope in power-down and XL_HM_MODE = 0, and "when ULP mode is
     * switched ON/OFF, the accelerometer must be configured in power-down condition": so both off,
     * then the mode bits, then the accelerometer back on at 12.5 Hz. The interrupt set-up is
     * written again: a part that reset since boot would otherwise sleep on its defaults. */
    esp_err_t err = wr8(REG_CTRL2_G, 0x00);
    err = err == ESP_OK ? wr8(REG_CTRL1_XL, 0x00) : err;
    err = err == ESP_OK ? wr8(REG_CTRL6_C, CTRL6_ULP) : err;
    err = err == ESP_OK ? wr8(REG_CTRL5_C, CTRL5_ULP) : err;
    err = err == ESP_OK ? write_common() : err;
    err = err == ESP_OK ? wr8(REG_CTRL1_XL, CTRL1_XL_SLEEP) : err;
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "LSM6DSO sleep configuration failed (%s): it may stay in its awake mode", esp_err_to_name(err));
    }
    /* the mode change itself can trip the slope filter: let it settle, then clear the latch */
    vTaskDelay(pdMS_TO_TICKS(SLEEP_SETTLE_MS));
    gpio_set_direction(PIN_IMU_INT1, GPIO_MODE_INPUT);
    for (int i = 0; i < 2; i++) {
        clear_latch(); /* INT_CLR_ON_READ: INT1 is high again as the read ends */
        if (gpio_get_level(PIN_IMU_INT1)) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(100)); /* still being moved? once more */
    }
    /* low for good: not configured (INT1 is then an input with a pull-down), or still in motion */
    ESP_LOGW(TAG, "IMU INT1 still low after clearing: pickup wake disabled for this sleep");
    return false;
}
