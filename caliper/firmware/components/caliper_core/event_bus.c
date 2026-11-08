/* Event bus: a dedicated esp_event loop with its own task. */
#include "caliper_core.h"

#include "esp_log.h"

ESP_EVENT_DEFINE_BASE(CALIPER_EVENT);

static const char *TAG = "bus";
static esp_event_loop_handle_t s_loop;

esp_err_t bus_init(void);

esp_err_t bus_init(void)
{
    if (s_loop) {
        return ESP_OK;
    }
    esp_event_loop_args_t args = {
        .queue_size = 32,
        .task_name = "bus",
        .task_priority = 6,
        .task_stack_size = 6144,
        .task_core_id = 0,
    };
    return esp_event_loop_create(&args, &s_loop);
}

esp_err_t bus_post(cal_evt_t id, const void *data, size_t len)
{
    if (!s_loop) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t err = esp_event_post_to(s_loop, CALIPER_EVENT, (int32_t)id, data, len, pdMS_TO_TICKS(50));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "post %d dropped: %s", (int)id, esp_err_to_name(err));
    }
    return err;
}

esp_err_t bus_subscribe(cal_evt_t id, esp_event_handler_t handler, void *arg)
{
    if (!s_loop) {
        return ESP_ERR_INVALID_STATE;
    }
    int32_t eid = (int32_t)id < 0 ? ESP_EVENT_ANY_ID : (int32_t)id;
    return esp_event_handler_instance_register_with(s_loop, CALIPER_EVENT, eid, handler, arg, NULL);
}
