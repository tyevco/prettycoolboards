/* power: BQ25180 charger, MAX17048 fuel gauge, LIS2DW12 wake-up, temperature guard. */
#include "power.h"

#include <string.h>

#include "board_pins.h"
#include "driver/temperature_sensor.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"

static const char *TAG = "power";

#define I2C_HZ      400000
#define I2C_TIMEOUT 50 /* ms */

/* ---- BQ25180 registers (SLUSE99) ---- */
#define BQ_STAT0      0x00
#define BQ_STAT1      0x01
#define BQ_FLAG0      0x02
#define BQ_VBAT_CTRL  0x03
#define BQ_ICHG_CTRL  0x04
#define BQ_CHARGECTL0 0x05
#define BQ_CHARGECTL1 0x06
#define BQ_IC_CTRL    0x07
#define BQ_TMR_ILIM   0x08
#define BQ_SHIP_RST   0x09
#define BQ_SYS_REG    0x0A
#define BQ_TS_CONTROL 0x0B

#define BQ_ICHG_CHG_DIS 0x80
#define BQ_ILIM_100MA   0xC9 /* MR 20 s, autowake 1 s, ILIM code 001 = 100 mA */
#define BQ_ILIM_500MA   0xCD /* ILIM code 101 = 500 mA */
#if CONFIG_CALIPER_CHG_TS_ENABLE
#define BQ_IC_CTRL_VAL 0x97  /* TS_EN, VLOWV 3.0 V, VRCH 100 mV, 2XTMR, 6 h timer, watchdog off */
#else
#define BQ_IC_CTRL_VAL 0x17  /* TS_EN = 0: only for a board without the RT1 NTC */
#endif

/* ---- MAX17048 ---- */
#define FG_VCELL   0x02
#define FG_SOC     0x04
#define FG_VERSION 0x08
#define FG_VRESET  0x18

/* ---- LIS2DW12 ---- */
#define IMU_WHO_AM_I     0x0F
#define IMU_WHO_AM_I_VAL 0x44
#define IMU_CTRL1        0x20
#define IMU_CTRL2        0x21
#define IMU_CTRL3        0x22
#define IMU_CTRL4_INT1   0x23
#define IMU_CTRL6        0x25
#define IMU_WAKE_UP_THS  0x34
#define IMU_WAKE_UP_DUR  0x35
#define IMU_WAKE_UP_SRC  0x38
#define IMU_ALL_INT_SRC  0x3B
#define IMU_CTRL7        0x3F

/* Charge temperature guard on the ESP32-S3 die (no NTC). The die runs a few degC above the
 * cell; limits are therefore a little wider than the 0..45 degC cell range (TVP). */
#define GUARD_COLD_C   2.0f
#define GUARD_HOT_C    55.0f
#define GUARD_HYST_C   3.0f
#define CHARGER_GRACE_US (3 * 1000 * 1000) /* no enumeration within 3 s of VBUS: a charger */

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_bq, s_fg, s_imu;
static temperature_sensor_handle_t s_tsens;
static bool s_chg_ok, s_fg_ok, s_imu_ok;
static bool s_usb_configured;
static bool s_guard_dis;
static int64_t s_vbus_since;
static uint8_t s_ilim = BQ_ILIM_100MA;

static esp_err_t wr8(i2c_master_dev_handle_t d, uint8_t reg, uint8_t v)
{
    uint8_t b[2] = {reg, v};
    return i2c_master_transmit(d, b, 2, I2C_TIMEOUT);
}

static esp_err_t rd(i2c_master_dev_handle_t d, uint8_t reg, uint8_t *v, size_t n)
{
    return i2c_master_transmit_receive(d, &reg, 1, v, n, I2C_TIMEOUT);
}

static uint8_t ichg_code(int ma)
{
    /* ICHG = code + 5 mA for codes 0..31, = 40 + (code - 31) * 10 mA above (SLUSE99 ICHG_CTRL) */
    if (ma <= 35) {
        return (uint8_t)(ma < 5 ? 0 : ma - 5);
    }
    int code = 31 + (ma - 40) / 10;
    return (uint8_t)(code > 127 ? 127 : code);
}

static uint8_t ichg_value(void)
{
    return (uint8_t)(ichg_code(CONFIG_CALIPER_CHARGE_MA) | (s_guard_dis ? BQ_ICHG_CHG_DIS : 0));
}

/* Writes the whole table; IC_CTRL first because it disables the watchdog that starts on the
 * first I2C transaction (dial-me-spinner docs/firmware.md §13.1). */
static esp_err_t bq_write_table(void)
{
    const struct {
        uint8_t reg, val;
    } table[] = {
        {BQ_IC_CTRL, BQ_IC_CTRL_VAL},
        {BQ_VBAT_CTRL, 0x46},  /* 4.20 V */
        {BQ_ICHG_CTRL, ichg_value()}, /* 250 mA (SPEC §1) -> code 52 = 0x34 */
        {BQ_CHARGECTL0, 0x20}, /* IPRECHG 2 x ITERM, ITERM 10 %, VINDPM 4.2 V, TREG 100 degC */
        {BQ_CHARGECTL1, 0x92}, /* BATOCP 1.5 A, BUVLO 3.0 V, CHG_STATUS int on, ILIM int masked */
        {BQ_TMR_ILIM, s_ilim}, /* 100 mA until a host configures us, then 500 mA */
        /* EN_PUSH = 0: TS/MR carries the NTC and no button on rev A, and the push-button scan
         * costs 1 uA in battery mode (SLUSE99C IQ_BAT 3 uA with it disabled, 4 uA enabled; the
         * SPEC §3 sleep budget assumes 3 uA). Long press action = HW reset, WAKE1 300 ms, WAKE2 2 s.
         * (dial-me-spinner writes 0x09 because it has a button on TS/MR.) */
        {BQ_SHIP_RST, 0x08},
        {BQ_SYS_REG, 0x20},    /* SYS 4.4 V on USB; the buck-boost accepts 2.2-5.5 V */
#if CONFIG_CALIPER_CHG_TS_ENABLE
        {BQ_TS_CONTROL, 0x90},
#endif
    };
    for (size_t i = 0; i < sizeof(table) / sizeof(table[0]); i++) {
        ESP_RETURN_ON_ERROR(wr8(s_bq, table[i].reg, table[i].val), TAG, "bq reg 0x%02x", table[i].reg);
    }
    uint8_t st[3];
    return rd(s_bq, BQ_STAT0, st, 3); /* clears the flags */
}

static esp_err_t imu_init(void)
{
    uint8_t who = 0;
    ESP_RETURN_ON_ERROR(rd(s_imu, IMU_WHO_AM_I, &who, 1), TAG, "imu who");
    if (who != IMU_WHO_AM_I_VAL) {
        ESP_LOGE(TAG, "LIS2DW12 WHO_AM_I 0x%02x", who);
        return ESP_ERR_NOT_FOUND;
    }
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL2, 0x0C), TAG, "ctrl2");     /* BDU, auto-increment */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL1, 0x20), TAG, "ctrl1");     /* 12.5 Hz, low-power mode 1 */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL6, 0x00), TAG, "ctrl6");     /* +-2 g */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL3, 0x18), TAG, "ctrl3");     /* latched, active low, push-pull */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_WAKE_UP_DUR, 0x00), TAG, "wu dur");
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_WAKE_UP_THS, 0x02), TAG, "wu ths"); /* 2 x 31.25 mg */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL4_INT1, 0x20), TAG, "int1");  /* wake-up on INT1 */
    ESP_RETURN_ON_ERROR(wr8(s_imu, IMU_CTRL7, 0x20), TAG, "ctrl7");     /* interrupts enable */
    uint8_t src;
    return rd(s_imu, IMU_ALL_INT_SRC, &src, 1);
}

static esp_err_t add_dev(uint8_t addr, i2c_master_dev_handle_t *out)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = I2C_HZ,
    };
    return i2c_master_bus_add_device(s_bus, &cfg, out);
}

esp_err_t power_init(void)
{
    i2c_master_bus_config_t bcfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false, /* 4.7 k on the board */
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bcfg, &s_bus), TAG, "i2c bus");
    ESP_ERROR_CHECK(add_dev(I2C_ADDR_BQ25180, &s_bq));
    ESP_ERROR_CHECK(add_dev(I2C_ADDR_MAX17048, &s_fg));
    ESP_ERROR_CHECK(add_dev(I2C_ADDR_LIS2DW12, &s_imu));

    s_chg_ok = bq_write_table() == ESP_OK;
    uint8_t ver[2] = {0, 0};
    s_fg_ok = rd(s_fg, FG_VERSION, ver, 2) == ESP_OK;
    if (s_fg_ok) {
        /* VRESET/ID (0x18): set Dis (bit 0 of the MSB) so the reset comparator is off in
         * hibernate (SPEC §3 sleep budget: 3 uA instead of 4 uA, 19-6171 IDD0). The register is
         * 16 bits wide: write both bytes back, the LSB (ID) is read-only. */
        uint8_t vr[2];
        if (rd(s_fg, FG_VRESET, vr, 2) == ESP_OK && !(vr[0] & 0x01)) {
            uint8_t w[3] = {FG_VRESET, (uint8_t)(vr[0] | 0x01), vr[1]};
            if (i2c_master_transmit(s_fg, w, sizeof(w), I2C_TIMEOUT) != ESP_OK) {
                ESP_LOGW(TAG, "MAX17048 VRESET.Dis write failed");
            }
        }
    }
    s_imu_ok = imu_init() == ESP_OK;
    ESP_LOGI(TAG, "BQ25180 %s, MAX17048 %s (0x%02x%02x), LIS2DW12 %s", s_chg_ok ? "ok" : "MISSING",
             s_fg_ok ? "ok" : "MISSING", ver[0], ver[1], s_imu_ok ? "ok" : "MISSING");

    temperature_sensor_config_t tcfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10, 80);
    if (temperature_sensor_install(&tcfg, &s_tsens) == ESP_OK) {
        temperature_sensor_enable(s_tsens);
    } else {
        s_tsens = NULL;
    }
    return ESP_OK;
}

i2c_master_bus_handle_t power_i2c_bus(void)
{
    return s_bus;
}

void power_usb_configured(bool configured)
{
    s_usb_configured = configured;
    uint8_t want = configured ? BQ_ILIM_500MA : BQ_ILIM_100MA;
    if (s_chg_ok && want != s_ilim) {
        s_ilim = want;
        wr8(s_bq, BQ_TMR_ILIM, s_ilim);
    }
}

void power_poll(power_status_t *o)
{
    memset(o, 0, sizeof(*o));
    o->charger_ok = s_chg_ok;
    o->gauge_ok = s_fg_ok;
    o->imu_ok = s_imu_ok;

    if (s_fg_ok) {
        uint8_t b[2];
        if (rd(s_fg, FG_VCELL, b, 2) == ESP_OK) {
            o->vcell_mv = (uint16_t)((((uint32_t)b[0] << 8) | b[1]) * 78125u / 1000000u); /* 78.125 uV/LSB */
        }
        if (rd(s_fg, FG_SOC, b, 2) == ESP_OK) {
            o->soc_pct = b[0] > 100 ? 100 : b[0]; /* 1 %/LSB in the high byte */
        }
    }

    if (s_tsens) {
        temperature_sensor_get_celsius(s_tsens, &o->die_c);
    }

    if (s_chg_ok) {
        uint8_t st[3];
        if (rd(s_bq, BQ_STAT0, st, 3) == ESP_OK) {
            o->stat0 = st[0];
            o->stat1 = st[1];
            o->flag0 = st[2];
            o->vbus = st[0] & 0x01;            /* VIN_PGOOD_STAT */
            o->chg_stat = (st[0] >> 5) & 0x03; /* CHG_STAT */
            o->charging = o->chg_stat == 1 || o->chg_stat == 2;
            o->ts_open = (st[0] & 0x80) != 0; /* TS_OPEN_STAT */
        }
        /* a BQ reset returns IC_CTRL to its POR value: rewrite the table */
        uint8_t ic;
        if (rd(s_bq, BQ_IC_CTRL, &ic, 1) == ESP_OK && ic != BQ_IC_CTRL_VAL) {
            ESP_LOGW(TAG, "BQ25180 reset detected (IC_CTRL 0x%02x), rewriting", ic);
            bq_write_table();
        }
        /* VBUS without enumeration for 3 s: a dedicated charger, allow 500 mA */
        int64_t now = esp_timer_get_time();
        if (!o->vbus) {
            s_vbus_since = 0;
            if (s_ilim != BQ_ILIM_100MA) {
                s_ilim = BQ_ILIM_100MA; /* re-arm for the next plug-in */
                wr8(s_bq, BQ_TMR_ILIM, s_ilim);
            }
        } else if (s_vbus_since == 0) {
            s_vbus_since = now;
        } else if (!s_usb_configured && s_ilim != BQ_ILIM_500MA && now - s_vbus_since > CHARGER_GRACE_US) {
            s_ilim = BQ_ILIM_500MA;
            wr8(s_bq, BQ_TMR_ILIM, s_ilim);
        }
        /* die-temperature charge guard */
        bool dis = s_guard_dis;
#if CONFIG_CALIPER_CHG_TS_ENABLE
        /* an open NTC can disable TS monitoring instead of reading cold (dial-me-spinner §13.1) */
        if (o->ts_open) {
            dis = true;
        } else
#endif
        if (s_tsens) {
            if (!dis && (o->die_c < GUARD_COLD_C || o->die_c > GUARD_HOT_C)) {
                dis = true;
            } else if (dis && o->die_c > GUARD_COLD_C + GUARD_HYST_C && o->die_c < GUARD_HOT_C - GUARD_HYST_C) {
                dis = false;
            }
        }
        if (dis != s_guard_dis) {
            s_guard_dis = dis;
            wr8(s_bq, BQ_ICHG_CTRL, ichg_value());
            ESP_LOGW(TAG, "charging %s (die %.1f C)", dis ? "disabled" : "enabled", (double)o->die_c);
        }
        o->chg_disabled = s_guard_dis;
    }
}

void power_ship_mode(void)
{
    if (s_chg_ok) {
        /* EN_RST_SHIP = 01: shutdown mode, wake on adapter insert only (SLUSE99C Table 8-18).
         * TS/MR has no button on rev A, so the button-wake ship mode (10) would only cost
         * IBAT_SHIP 3.2 uA for its push-button scan instead of IBAT_SHUTDOWN 15 nA. */
        wr8(s_bq, BQ_SHIP_RST, 0x28);
    }
}

/* Clears a latched wake-up interrupt so INT1 is high again before sleeping. */
bool power_imu_clear(void);
bool power_imu_clear(void)
{
    if (!s_imu_ok) {
        return false;
    }
    uint8_t src;
    rd(s_imu, IMU_WAKE_UP_SRC, &src, 1);
    rd(s_imu, IMU_ALL_INT_SRC, &src, 1);
    return true;
}
