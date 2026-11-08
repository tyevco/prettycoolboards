idf_component_register(
    SRCS "store.c"
    INCLUDE_DIRS "include"
    REQUIRES measure nvs_flash vfs
    PRIV_REQUIRES esp_partition)
