idf_component_register(
    SRCS "wifi.c" "web.c" "push.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES board measure caliper_core store esp_wifi esp_netif esp_http_server esp_http_client mqtt
                  esp_timer mbedtls freertos)
