idf_component_register(
    SRCS "ui_panel.c" "ui_screens.c" "ui_input.c"
    INCLUDE_DIRS "include"
    REQUIRES measure
    PRIV_REQUIRES board caliper_core power esp_lcd esp_driver_spi esp_app_format)
