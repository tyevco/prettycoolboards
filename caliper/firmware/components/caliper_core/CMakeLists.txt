idf_component_register(
    SRCS "caliper_core.c" "event_bus.c"
    INCLUDE_DIRS "include"
    REQUIRES measure store esp_event
    PRIV_REQUIRES esp_timer board)
