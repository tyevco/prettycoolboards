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

bool ui_lock(void)
{
    return lvgl_port_lock(100);
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
    if (ui_lock()) {
        ui_screens_create();
        ui_unlock();
    }
    bus_subscribe(CAL_EVT_TOAST, on_toast, NULL);
    ESP_LOGI(TAG, "display up");
    return ESP_OK;
}

void ui_sleep(void)
{
    if (s_panel) {
        esp_lcd_panel_disp_on_off(s_panel, false);
        esp_lcd_panel_disp_sleep(s_panel, true);
    }
}
