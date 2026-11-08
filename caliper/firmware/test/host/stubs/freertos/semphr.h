/* Host-test stub (see FreeRTOS.h). */
#pragma once

#include "freertos/FreeRTOS.h"

typedef void *SemaphoreHandle_t;
static int host_sem_dummy;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void)
{
    return &host_sem_dummy;
}
static inline int xSemaphoreTake(SemaphoreHandle_t s, TickType_t t)
{
    (void)s;
    (void)t;
    return pdTRUE;
}
static inline int xSemaphoreGive(SemaphoreHandle_t s)
{
    (void)s;
    return pdTRUE;
}
