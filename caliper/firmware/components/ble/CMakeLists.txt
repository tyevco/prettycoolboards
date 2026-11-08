idf_component_register(
    SRCS "ble.c" "ble_gatt.c" "ble_std.c" "ble_worker.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES bt board measure caliper_core store esp_timer esp_app_format)
