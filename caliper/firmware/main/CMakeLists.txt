idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "." "proto"
    PRIV_REQUIRES board measure caliper_core store sensor_mag sensor_cap power ui ble caliper_wifi caliper_usb
                  nvs_flash esp_netif esp_event esp_timer esp_pm esp_driver_gpio esp_app_format)
