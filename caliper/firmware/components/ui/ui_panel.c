/* ST7789 panel over SPI2 (esp_lcd) and the LVGL port. */
#include "board_pins.h"
#include "caliper_core.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_st7789.h"
#include "esp_log.h"
#include "esp_lvgl_port.h"
#include "ui.h"

static const char *TAG = "ui";

#define LCD_HOST    SPI2_HOST
#define LCD_HRES    240 /* landscape */
#define LCD_VRES    135
#define LCD_PCLK_HZ (40 * 1000 * 1000)
/* 1.14 in 135 x 240 glass on the 240 x 320 ST7789 RAM: offsets in landscape (TVP: the common
 * modules use 40/53 or 40/52 depending on the rotation) */
#define LCD_GAP_X 40
#define LCD_GAP_Y 53

static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static lv_display_t *s_disp;
/* LVGL port running and the screens created. lvgl_port_lock() asserts (abort, reboot loop) when
 * lvgl_port_init() never ran, which is what happened when the panel failed to initialise and the
 * button task then called ui_lock() (2026-11-07 review). */
static volatile bool s_ready;

bool ui_ready(void)
{
    return s_ready;
}

bool ui_lock(void)
{
    return s_ready && lvgl_port_lock(100);
}

void ui_unlock(void)
{
    lvgl_port_unlock();
}

static void on_toast(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    if (ui_lock()) {
        ui_toast((const char *)data);
        ui_unlock();
    }
}

esp_err_t ui_init(void)
{
    spi_bus_config_t bus = {
        .sclk_io_num = PIN_LCD_SCK,
        .mosi_io_num = PIN_LCD_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_HRES * 30 * 2,
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(LCD_HOST, &bus, SPI_DMA_CH_AUTO), TAG, "spi bus");

    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = PIN_LCD_DC,
        .cs_gpio_num = PIN_LCD_CS_N,
        .pclk_hz = LCD_PCLK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_cfg, &s_io), TAG,
                        "panel io");
    esp_lcd_panel_dev_config_t pcfg = {
        .reset_gpio_num = PIN_LCD_RST_N,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7789(s_io, &pcfg, &s_panel), TAG, "st7789");
    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true)); /* IPS panels need inversion */
    ESP_ERROR_CHECK(esp_lcd_panel_set_gap(s_panel, LCD_GAP_X, LCD_GAP_Y));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

    lvgl_port_cfg_t lcfg = ESP_LVGL_PORT_INIT_CONFIG();
    lcfg.task_priority = 4;
    lcfg.task_stack = 6144;
    /* the port default is no affinity: keep rendering off core 1 (sensor task, capacitive burst) */
    lcfg.task_affinity = 0;
    ESP_RETURN_ON_ERROR(lvgl_port_init(&lcfg), TAG, "lvgl port");

    lvgl_port_display_cfg_t dcfg = {
        .io_handle = s_io,
        .panel_handle = s_panel,
        .buffer_size = LCD_HRES * 30,
        .double_buffer = true,
        .hres = LCD_HRES,
        .vres = LCD_VRES,
        .monochrome = false,
        .color_format = LV_COLOR_FORMAT_RGB565,
        .rotation = {.swap_xy = true, .mirror_x = false, .mirror_y = true},
        .flags = {.buff_dma = true, .swap_bytes = true},
    };
    s_disp = lvgl_port_add_disp(&dcfg);
    if (!s_disp) {
        return ESP_FAIL;
    }
    /* wait as long as it takes here: with a timeout the screens could be left uncreated while the
     * LVGL timers and the toast handler assume they exist */
    if (!lvgl_port_lock(0)) {
        return ESP_FAIL;
    }
    ui_screens_create();
    s_ready = true;
    lvgl_port_unlock();
    bus_subscribe(CAL_EVT_TOAST, on_toast, NULL);
    ESP_LOGI(TAG, "display up");
    return ESP_OK;
}

/* Bring-up test pattern ("bu lcd", docs/bringup.md): eight full-height colour bars (white, yellow,
 * cyan, green, magenta, red, blue, black) inset 3-4 px in a black field, a 1 px white frame on the
 * outermost pixels (a wrong LCD_GAP_X / _Y cuts one edge of it off and shows noise on the opposite
 * side), and corner labels (a wrong rotation / mirror puts "TOP LEFT" elsewhere or mirrors it).
 * Drawn on LVGL's top layer over the normal screens; off removes it. */
static lv_obj_t *s_pattern;

esp_err_t ui_test_pattern(bool on)
{
    static const uint32_t bars[8] = {0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00, 0xFF00FF, 0xFF0000, 0x0000FF, 0x000000};
    if (!ui_lock()) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_pattern) {
        lv_obj_delete(s_pattern);
        s_pattern = NULL;
    }
    if (on) {
        lv_obj_t *p = lv_obj_create(lv_layer_top());
        lv_obj_remove_style_all(p);
        lv_obj_set_pos(p, 0, 0);
        lv_obj_set_size(p, LCD_HRES, LCD_VRES);
        lv_obj_set_style_bg_color(p, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(p, lv_color_white(), 0);
        lv_obj_set_style_border_width(p, 1, 0);
        lv_obj_set_style_border_opa(p, LV_OPA_COVER, 0);
        lv_obj_remove_flag(p, LV_OBJ_FLAG_SCROLLABLE);
        for (int i = 0; i < 8; i++) {
            lv_obj_t *b = lv_obj_create(p);
            lv_obj_remove_style_all(b);
            lv_obj_set_pos(b, 4 + 29 * i, 3);
            lv_obj_set_size(b, 29, LCD_VRES - 6);
            lv_obj_set_style_bg_color(b, lv_color_hex(bars[i]), 0);
            lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        }
        static const char *const txt[2] = {"TOP LEFT", "BR"};
        for (int i = 0; i < 2; i++) {
            lv_obj_t *l = lv_label_create(p);
            lv_label_set_text(l, txt[i]);
            lv_obj_set_style_text_color(l, lv_color_white(), 0);
            lv_obj_set_style_bg_color(l, lv_color_black(), 0);
            lv_obj_set_style_bg_opa(l, LV_OPA_COVER, 0);
            lv_obj_set_style_pad_all(l, 2, 0);
            lv_obj_align(l, i ? LV_ALIGN_BOTTOM_RIGHT : LV_ALIGN_TOP_LEFT, i ? -5 : 5, i ? -5 : 5);
        }
        s_pattern = p;
    }
    ui_unlock();
    return ESP_OK;
}

void ui_sleep(void)
{
    /* Stop LVGL first: the panel commands below share the SPI device with LVGL's flushes, which run
     * in the LVGL task, and an SPI device's transactions must not be issued from two tasks at once.
     * Holding the lock means no flush is being started; esp_lcd's tx_param waits for the queued
     * colour transfers to finish before it sends a command. (Before: called from the bus or app task
     * with no lock, possibly in the middle of a frame.) */
    if (s_ready && lvgl_port_lock(500)) {
        lvgl_port_stop();
        s_ready = false;
        lvgl_port_unlock();
    }
    if (s_panel) {
        esp_lcd_panel_disp_on_off(s_panel, false);
        esp_lcd_panel_disp_sleep(s_panel, true);
    }
}
