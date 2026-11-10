idf_component_register(
    SRCS "power.c" "imu.c" "outputs.c" "sleep.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_driver_i2c measure
    PRIV_REQUIRES board esp_driver_gpio esp_driver_ledc esp_driver_tsens esp_timer)
