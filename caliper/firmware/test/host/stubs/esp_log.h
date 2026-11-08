/* Host-test stub: ESP-IDF logging compiled out (arguments still type-checked). */
#pragma once

#include <stdio.h>

#define ESP_HOST_LOG_(tag, ...) \
    do {                        \
        if (0) {                \
            (void)(tag);        \
            printf(__VA_ARGS__); \
        }                       \
    } while (0)
#define ESP_LOGE(tag, ...) ESP_HOST_LOG_(tag, __VA_ARGS__)
#define ESP_LOGW(tag, ...) ESP_HOST_LOG_(tag, __VA_ARGS__)
#define ESP_LOGI(tag, ...) ESP_HOST_LOG_(tag, __VA_ARGS__)
#define ESP_LOGD(tag, ...) ESP_HOST_LOG_(tag, __VA_ARGS__)
