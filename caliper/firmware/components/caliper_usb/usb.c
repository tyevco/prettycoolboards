/* TinyUSB composite (CDC + MSC) or the USB-Serial-JTAG fallback. */
#include <stdio.h>

#include "caliper_core.h"
#include "caliper_usb.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "power.h"
#include "sdkconfig.h"

#if CONFIG_CALIPER_USB_TINYUSB
#include "tinyusb.h"
#include "tusb_cdc_acm.h"
#include "tusb.h"
#include "tusb_console.h"
#else
#include "driver/usb_serial_jtag.h"
#endif

static const char *TAG = "usb";
static bool s_host;

bool caliper_usb_host(void)
{
    return s_host;
}

#if CONFIG_CALIPER_USB_TINYUSB

static void cdc_rx(int itf, cdcacm_event_t *event)
{
    (void)event;
    uint8_t buf[64];
    size_t n = 0;
    while (tinyusb_cdcacm_read(itf, buf, sizeof(buf), &n) == ESP_OK && n > 0) {
        cli_feed((const char *)buf, n);
    }
}

esp_err_t caliper_usb_init(void)
{
#if CONFIG_CALIPER_USB_MSC
    /* MSC storage must be set up before the driver builds the descriptors */
    if (msc_init() != ESP_OK) {
        ESP_LOGW(TAG, "MSC unavailable; CDC only");
    }
#endif
    /* all NULL: the default device/string/configuration descriptors, built from Kconfig
     * (TINYUSB_DESC_*) and the enabled classes (CDC + MSC) */
    const tinyusb_config_t cfg = {0};
    esp_err_t err = tinyusb_driver_install(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "tinyusb_driver_install: %s", esp_err_to_name(err));
        return err;
    }
    tinyusb_config_cdcacm_t acm = {
        .usb_dev = TINYUSB_USBDEV_0,
        .cdc_port = TINYUSB_CDC_ACM_0,
        .callback_rx = cdc_rx,
    };
    err = tusb_cdc_acm_init(&acm);
    if (err != ESP_OK) {
        return err;
    }
    esp_tusb_init_console(TINYUSB_CDC_ACM_0); /* stdout/stderr (logs) -> CDC */
    cli_start();
#if CONFIG_CALIPER_USB_MSC
    ESP_LOGI(TAG, "TinyUSB CDC + MSC up");
#else
    ESP_LOGI(TAG, "TinyUSB CDC up");
#endif
    return ESP_OK;
}

void caliper_usb_poll(void)
{
    bool host = tud_mounted();
    if (host != s_host) {
        s_host = host;
        core_set_usb_host(host);
        power_usb_configured(host);
        ESP_LOGI(TAG, "host %s", host ? "attached" : "gone");
#if CONFIG_CALIPER_USB_MSC
        if (host) {
            msc_export();
        }
#endif
        if (host) {
            core_activity();
        }
    }
}

#else /* USB-Serial-JTAG */

static void usj_task(void *arg)
{
    (void)arg;
    char buf[64];
    for (;;) {
        int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), pdMS_TO_TICKS(100));
        if (n > 0) {
            cli_feed(buf, (size_t)n);
        }
    }
}

esp_err_t caliper_usb_init(void)
{
    usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    esp_err_t err = usb_serial_jtag_driver_install(&cfg);
    if (err != ESP_OK) {
        return err;
    }
    cli_start();
    xTaskCreatePinnedToCore(usj_task, "usj", 3072, NULL, 3, NULL, 0);
    return ESP_OK;
}

void caliper_usb_poll(void)
{
}

#endif
