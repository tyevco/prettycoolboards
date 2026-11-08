/* ASCII -> HID usage table (US layout). Portable C. */
#include "hid_keymap.h"

#include <string.h>

bool hid_ascii_to_key(char ch, uint8_t *mod, uint8_t *usage)
{
    unsigned char c = (unsigned char)ch;
    *mod = 0;
    if (c >= 'a' && c <= 'z') {
        *usage = (uint8_t)(0x04 + (c - 'a'));
        return true;
    }
    if (c >= 'A' && c <= 'Z') {
        *mod = HID_MOD_LSHIFT;
        *usage = (uint8_t)(0x04 + (c - 'A'));
        return true;
    }
    if (c >= '1' && c <= '9') {
        *usage = (uint8_t)(0x1E + (c - '1'));
        return true;
    }
    switch (c) {
    case '0': *usage = 0x27; return true;
    case '\n': *usage = 0x28; return true; /* Enter */
    case '\t': *usage = 0x2B; return true;
    case ' ': *usage = 0x2C; return true;
    case '-': *usage = 0x2D; return true;
    case '=': *usage = 0x2E; return true;
    case ',': *usage = 0x36; return true;
    case '.': *usage = 0x37; return true;
    case '/': *usage = 0x38; return true;
    case ';': *usage = 0x33; return true;
    case '+': *mod = HID_MOD_LSHIFT; *usage = 0x2E; return true;
    case ':': *mod = HID_MOD_LSHIFT; *usage = 0x33; return true;
    case '"': *mod = HID_MOD_LSHIFT; *usage = 0x34; return true;
    default: return false;
    }
}

size_t hid_build_reports(const char *s, uint8_t (*out)[8], size_t max_reports)
{
    size_t n = 0;
    for (; *s && n + 2 <= max_reports; s++) {
        uint8_t mod, usage;
        if (!hid_ascii_to_key(*s, &mod, &usage)) {
            continue;
        }
        memset(out[n], 0, 8);
        out[n][0] = mod;
        out[n][2] = usage;
        n++;
        memset(out[n], 0, 8);
        n++;
    }
    return n;
}
