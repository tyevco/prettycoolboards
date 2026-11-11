# Bring-up checks on the USB console ("bu help", docs/bringup.md). bringup_eval.c is portable
# (also built by test/host).
idf_component_register(
    SRCS "bringup.c" "bringup_eval.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES board power store sensor_mag sensor_cap ui ble caliper_wifi caliper_core esp_driver_gpio esp_driver_i2c)
