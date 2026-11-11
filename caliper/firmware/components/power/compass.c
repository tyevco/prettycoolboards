/*
 * compass: the IIS2MDC 3-axis magnetometer (U61, I2C 0x1E, always-on +3V3). Its INT/DRDY pin is not
 * connected, so it is polled. Two jobs:
 *
 *   awake   continuous mode at 10 Hz, low-power, with offset cancellation, the low-pass filter and
 *           temperature compensation; polled at 10 Hz by the IMU sampler (imu.c) and fused by
 *           components/measure/orient.c into a magnetic heading that holds the relative yaw.
 *   asleep  power-down.
 *
 * Sources. Register addresses, bit positions, the WHO_AM_I value and the scale factor: ST's driver,
 * github.com/STMicroelectronics/iis2mdc-pid, iis2mdc_reg.h and iis2mdc_reg.c ("reg.h" / "reg.c";
 * the field names below are that header's). The sequence (soft reset, wait for the bit, configure;
 * the data-ready bit, then one plain 6-byte read) is ST's example iis2mdc_read_data_polling.c
 * (STMems_Standard_C_drivers, iis2mdc_STdC/examples). Currents: the datasheet, DocID030986 Rev 1:
 * 50 uA at 10 Hz in low-power mode with offset cancellation (100 uA in high-resolution mode),
 * 1.5 uA typical in power-down; RMS noise 9 mgauss in low-power mode, 6 mgauss with the low-pass
 * filter or offset cancellation. Nothing here has run on a board: all of it is TVP until one has.
 *
 * The part sits 11 mm from an O1 steel beam, next to the battery and its currents, on a tool that
 * rides a magnetic tape. What it reads is the local field, not the Earth's: orient.c gates every
 * sample on plausibility and the heading is never called north.
 */
#include "compass.h"

#include "board_pins.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "power.h"

static const char *TAG = "compass";

/* ================================================================================================
 * AXIS MAPPING, chip -> board: THE one place.
 *
 * Board frame (orient.h): +x along the beam toward the USB end, +y toward the buttons / top edge,
 * +z out of the display face. U61 sits on the top side at 0 deg, which SHOULD make chip X = board
 * +x, chip Y = board +y, chip Z = board +z: the identity. TVP: the chip's positive directions are a
 * drawing in the datasheet that has not been checked against the footprint, so this table is to be
 * verified on the first board with "bu compass" (which prints the chip's axes; north of the
 * magnetic equator the field points down: Z negative with the display up, and X largest with the
 * USB end toward north).
 *
 * board = row * chip. A wrong sign is fixed in these nine numbers and nowhere else. The table is
 * not passed through orient_mount_valid(): if the chip's frame turns out left-handed against the
 * board's, the right table here is a mirror, not a rotation.
 * ============================================================================================== */
static const orient_mount_t s_mount = {{
    {1, 0, 0}, /* board +x (beam, toward USB)        = chip +X (TVP) */
    {0, 1, 0}, /* board +y (toward the buttons)      = chip +Y (TVP) */
    {0, 0, 1}, /* board +z (out of the display face) = chip +Z (TVP) */
}};

/* ---- registers (reg.h) ---------------------------------------------------------------------- */
#define REG_WHO_AM_I 0x4F /* IIS2MDC_WHO_AM_I */
#define REG_CFG_A    0x60 /* IIS2MDC_CFG_REG_A: comp_temp_en 7, reboot 6, soft_rst 5, lp 4, odr 3:2, md 1:0 */
#define REG_CFG_B    0x61 /* IIS2MDC_CFG_REG_B: off_canc_one_shot 4, int_on_dataoff 3, set_rst 2:1, lpf 0 */
#define REG_CFG_C    0x62 /* IIS2MDC_CFG_REG_C: int_on_pin 6, i2c_dis 5, bdu 4, ble 3, self_test 1, drdy_on_pin 0 */
#define REG_STATUS   0x67 /* IIS2MDC_STATUS_REG: zyxor 7, zor 6, yor 5, xor 4, zyxda 3, zda 2, yda 1, xda 0 */
#define REG_OUTX_L   0x68 /* IIS2MDC_OUTX_L_REG; then OUTX_H 69h, OUTY_L/H 6Ah-6Bh, OUTZ_L/H 6Ch-6Dh */

#define WHO_AM_I_VAL 0x40 /* IIS2MDC_ID */

#define CFG_A_SOFT_RST 0x20
/* awake: comp_temp_en, lp = 1 (low-power), odr 00 = IIS2MDC_ODR_10Hz, md 00 = IIS2MDC_CONTINUOUS_MODE */
#define CFG_A_RUN   0x90
/* asleep: the same with md 10 = IIS2MDC_POWER_DOWN */
#define CFG_A_SLEEP 0x92
/* set_rst 01 = IIS2MDC_SENS_OFF_CANC_EVERY_ODR (offset cancellation at every sample), lpf = 1 */
#define CFG_B_VAL 0x03
/* bdu (an output pair never mixes two samples); ble = 0: low byte first; i2c_dis = 0; no interrupt
 * or data-ready on the pin, which is not connected */
#define CFG_C_VAL 0x10
#define STATUS_ZYXDA 0x08

/* reg.c iis2mdc_from_lsb_to_mgauss(): 1.5 mgauss/LSB, and 1 mgauss = 0.1 uT. Full scale is
 * +-32768 LSB = +-4915 uT: the Earth's 25-65 uT is a few hundred LSB. */
#define UT_PER_LSB 0.15f

#define I2C_HZ      400000
#define I2C_TIMEOUT 50 /* ms */

static i2c_master_dev_handle_t s_dev;
static bool s_ok; /* answered with the right WHO_AM_I and took the configuration */

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static power_compass_sample_t s_last; /* under s_mux */

static esp_err_t wr8(uint8_t reg, uint8_t v)
{
    uint8_t b[2] = {reg, v};
    return i2c_master_transmit(s_dev, b, 2, I2C_TIMEOUT);
}

/* Several bytes in one read: the register address increments by itself (ST's example reads the six
 * output bytes with one plain I2C memory read at 68h). */
static esp_err_t rd(uint8_t reg, uint8_t *v, size_t n)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, v, n, I2C_TIMEOUT);
}

esp_err_t power_compass_init(i2c_master_bus_handle_t bus)
{
    /* a probe first: on a board without U61 this is the one line the log gets */
    if (i2c_master_probe(bus, I2C_ADDR_IIS2MDC, I2C_TIMEOUT) != ESP_OK) {
        ESP_LOGW(TAG, "no IIS2MDC at 0x%02x: no magnetic heading", I2C_ADDR_IIS2MDC);
        return ESP_ERR_NOT_FOUND;
    }
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = I2C_ADDR_IIS2MDC,
        .scl_speed_hz = I2C_HZ,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &cfg, &s_dev), TAG, "add");

    uint8_t who = 0;
    ESP_RETURN_ON_ERROR(rd(REG_WHO_AM_I, &who, 1), TAG, "who");
    if (who != WHO_AM_I_VAL) {
        ESP_LOGE(TAG, "IIS2MDC WHO_AM_I 0x%02x (0x%02x expected)", who, WHO_AM_I_VAL);
        return ESP_ERR_NOT_FOUND;
    }

    /* The chip sits on the always-on rail: after a deep sleep it is in power-down, after a crash in
     * whatever it had. Software reset to the defaults, wait for the bit to read 0 (ST's example
     * does exactly this), then configure. */
    ESP_RETURN_ON_ERROR(wr8(REG_CFG_A, CFG_A_SOFT_RST), TAG, "reset");
    uint8_t a = CFG_A_SOFT_RST;
    for (int i = 0; i < 10 && (a & CFG_A_SOFT_RST); i++) {
        vTaskDelay(pdMS_TO_TICKS(2));
        if (rd(REG_CFG_A, &a, 1) != ESP_OK) {
            a = CFG_A_SOFT_RST;
        }
    }
    if (a & CFG_A_SOFT_RST) {
        ESP_LOGE(TAG, "IIS2MDC software reset did not finish");
        return ESP_ERR_TIMEOUT;
    }

    ESP_RETURN_ON_ERROR(wr8(REG_CFG_B, CFG_B_VAL), TAG, "cfg b");
    ESP_RETURN_ON_ERROR(wr8(REG_CFG_C, CFG_C_VAL), TAG, "cfg c");
    ESP_RETURN_ON_ERROR(wr8(REG_CFG_A, CFG_A_RUN), TAG, "cfg a"); /* last: this starts it */
    s_ok = true;
    return ESP_OK;
}

esp_err_t power_compass_diag_read(uint8_t reg, uint8_t *buf, size_t n)
{
    return s_dev ? rd(reg, buf, n) : ESP_ERR_INVALID_STATE;
}

static int16_t le16(const uint8_t *b)
{
    return (int16_t)(uint16_t)(b[0] | (b[1] << 8));
}

bool power_compass_poll(orient_vec_t *b_ut)
{
    if (!s_ok) {
        return false;
    }
    /* STATUS_REG first: the part runs on its own 10 Hz clock, so now and then a poll comes before
     * the next sample, and the filter must not weigh one sample twice. Then X, Y, Z (68h-6Dh): one
     * burst, 16-bit two's complement, low byte first; BDU keeps each pair from one sample. */
    uint8_t st = 0, b[6];
    esp_err_t err = rd(REG_STATUS, &st, 1);
    if (err == ESP_OK && !(st & STATUS_ZYXDA)) {
        return false;
    }
    err = err == ESP_OK ? rd(REG_OUTX_L, b, sizeof(b)) : err;
    if (err != ESP_OK) {
        taskENTER_CRITICAL(&s_mux);
        s_last.errors++;
        taskEXIT_CRITICAL(&s_mux);
        return false; /* the next good sample carries the gap in its dt */
    }
    orient_vec_t chip = {
        (float)le16(&b[0]) * UT_PER_LSB,
        (float)le16(&b[2]) * UT_PER_LSB,
        (float)le16(&b[4]) * UT_PER_LSB,
    };
    *b_ut = orient_mount_apply(&s_mount, chip);

    taskENTER_CRITICAL(&s_mux);
    s_last.ut[0] = b_ut->x;
    s_last.ut[1] = b_ut->y;
    s_last.ut[2] = b_ut->z;
    s_last.samples++;
    taskEXIT_CRITICAL(&s_mux);
    return true;
}

bool power_compass_last(power_compass_sample_t *out)
{
    taskENTER_CRITICAL(&s_mux);
    *out = s_last;
    taskEXIT_CRITICAL(&s_mux);
    return out->samples > 0;
}

/* ---- sleep ---------------------------------------------------------------------------------- */

void power_compass_sleep_prepare(void)
{
    if (s_ok && wr8(REG_CFG_A, CFG_A_SLEEP) != ESP_OK) {
        ESP_LOGW(TAG, "IIS2MDC power-down failed: it may stay in continuous mode (50 uA)");
    }
}
