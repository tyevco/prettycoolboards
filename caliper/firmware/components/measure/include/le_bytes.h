/* Little-endian byte packing helpers (portable, no ESP-IDF). */
#pragma once

#include <stdint.h>

static inline void le_put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static inline void le_put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static inline void le_put_i32(uint8_t *p, int32_t v) { le_put_u32(p, (uint32_t)v); }

static inline uint16_t le_get_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

static inline uint32_t le_get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline int32_t le_get_i32(const uint8_t *p) { return (int32_t)le_get_u32(p); }
