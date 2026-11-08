# Portable core logic (no ESP-IDF APIs). Also compiled by test/host.
idf_component_register(
    SRCS "measure.c" "logrec.c" "gatt_codec.c" "settings.c" "csv.c" "buttons.c" "hid_keymap.c"
    INCLUDE_DIRS "include"
    REQUIRES board)
target_link_libraries(${COMPONENT_LIB} PUBLIC m)
