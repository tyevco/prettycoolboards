/* Applies the pin plan (pin_plan_table.c) to the pads. ESP-IDF only. See include/pin_plan.h. */
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_log.h"
#include "pin_plan.h"

static const char *TAG = "pin_plan";

static void set_rtc_pulls(const pin_plan_t *p, pp_mode_t mode)
{
    /* Deep sleep only: an RTC GPIO keeps its RTC IO pull bits, which act once ext1 (or an isolate)
     * routes the pad to the RTC mux. Write them too so neither pull set is left as it was. */
    if (mode != PP_MODE_SLEEP || !pin_plan_is_rtc_gpio(p->gpio)) {
        return;
    }
    const pp_state_t *s = &p->st[mode];
    gpio_num_t g = (gpio_num_t)p->gpio;
    if (s->pull == PP_PULL_UP) {
        rtc_gpio_pullup_en(g);
    } else {
        rtc_gpio_pullup_dis(g);
    }
    if (s->pull == PP_PULL_DOWN) {
        rtc_gpio_pulldown_en(g);
    } else {
        rtc_gpio_pulldown_dis(g);
    }
}

esp_err_t pin_plan_apply(pp_mode_t mode, uint64_t mask, unsigned flags)
{
    bool digital_held = false;
    int n = 0, held = 0;
    for (size_t i = 0; i < PIN_PLAN_COUNT; i++) {
        const pin_plan_t *p = &PIN_PLAN[i];
        const pp_state_t *s = &p->st[mode];
        if (!(mask & (1ULL << p->gpio)) || p->untouched || s->dir == PP_DIR_OFF || s->dir == PP_DIR_PERIPH) {
            continue;
        }
        gpio_num_t g = (gpio_num_t)p->gpio;
        gpio_mode_t gm = GPIO_MODE_DISABLE;
        switch (s->dir) {
        case PP_DIR_IN: gm = GPIO_MODE_INPUT; break;
        case PP_DIR_OUT: gm = GPIO_MODE_OUTPUT; break;
        case PP_DIR_OD: gm = GPIO_MODE_INPUT_OUTPUT_OD; break;
        default: gm = GPIO_MODE_DISABLE; break;
        }
        /* the level first, so an output never glitches to the old register value */
        if ((flags & PP_APPLY_LEVEL) && s->level != PP_LEVEL_NONE && (s->dir == PP_DIR_OUT || s->dir == PP_DIR_OD)) {
            gpio_set_level(g, s->level);
        }
        /* gpio_config, never gpio_reset_pin: in ESP-IDF v5.4 gpio_reset_pin() turns the pull-UP on
         * (esp_driver_gpio/src/gpio.c), which a pad driven low then fights (~73 uA per pad). */
        gpio_config_t c = {
            .pin_bit_mask = 1ULL << p->gpio,
            .mode = gm,
            .pull_up_en = s->pull == PP_PULL_UP ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
            .pull_down_en = s->pull == PP_PULL_DOWN ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        esp_err_t err = gpio_config(&c);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "GPIO%d (%s) %s: %s", p->gpio, p->net, pin_plan_mode_name(mode), esp_err_to_name(err));
            return err;
        }
        set_rtc_pulls(p, mode);
        n++;
        if ((flags & PP_APPLY_HOLD) && s->hold) {
            gpio_hold_en(g);
            held++;
            digital_held |= !pin_plan_is_rtc_gpio(p->gpio);
        }
    }
    if (digital_held) {
        gpio_deep_sleep_hold_en(); /* digital pads keep their hold only with this; ESP-IDF then isolates
                                    * every digital pad that is not held (sleep_gpio.c) */
    }
    ESP_LOGD(TAG, "%s: %d pins configured, %d held", pin_plan_mode_name(mode), n, held);
    return ESP_OK;
}

esp_err_t pin_plan_apply_pulls(pp_mode_t mode, uint64_t mask)
{
    for (size_t i = 0; i < PIN_PLAN_COUNT; i++) {
        const pin_plan_t *p = &PIN_PLAN[i];
        const pp_state_t *s = &p->st[mode];
        if (!(mask & (1ULL << p->gpio)) || p->untouched || s->dir == PP_DIR_OFF) {
            continue;
        }
        gpio_num_t g = (gpio_num_t)p->gpio;
        ESP_ERROR_CHECK_WITHOUT_ABORT(s->pull == PP_PULL_UP ? gpio_pullup_en(g) : gpio_pullup_dis(g));
        ESP_ERROR_CHECK_WITHOUT_ABORT(s->pull == PP_PULL_DOWN ? gpio_pulldown_en(g) : gpio_pulldown_dis(g));
        set_rtc_pulls(p, mode);
    }
    return ESP_OK;
}

void pin_plan_release_holds(void)
{
    gpio_deep_sleep_hold_dis();
    for (size_t i = 0; i < PIN_PLAN_COUNT; i++) {
        if (PIN_PLAN[i].st[PP_MODE_SLEEP].hold && !PIN_PLAN[i].untouched) {
            gpio_hold_dis((gpio_num_t)PIN_PLAN[i].gpio);
        }
    }
}
