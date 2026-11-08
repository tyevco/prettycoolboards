idf_component_register(
    SRCS "sensor_mag.c" "as5311_proto.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES board measure esp_driver_pcnt esp_driver_gpio)
