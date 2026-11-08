# EXPERIMENTAL capacitive scale. cap_demod.c is portable (also built by test/host).
idf_component_register(
    SRCS "sensor_cap.c" "cap_demod.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES board esp_adc esp_driver_gpio esp_timer esp_pm)
target_link_libraries(${COMPONENT_LIB} PRIVATE m)
