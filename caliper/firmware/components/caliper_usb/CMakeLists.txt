idf_component_register(
    SRCS "usb.c" "msc.c" "cli.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES caliper_core store power measure esp_partition wear_levelling fatfs esp_driver_usb_serial_jtag
                  esp_app_format)
