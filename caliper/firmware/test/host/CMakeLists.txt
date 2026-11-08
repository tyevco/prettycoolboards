# Host unit tests for the portable firmware modules (no ESP-IDF, nothing downloaded).
#   cmake -S test/host -B build-host && cmake --build build-host && ctest --test-dir build-host --output-on-failure
cmake_minimum_required(VERSION 3.16)
project(caliper_host_tests C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(FW ${CMAKE_CURRENT_LIST_DIR}/../..)

add_executable(caliper_tests
    test_main.c
    ${FW}/components/measure/measure.c
    ${FW}/components/measure/logrec.c
    ${FW}/components/measure/gatt_codec.c
    ${FW}/components/measure/settings.c
    ${FW}/components/measure/csv.c
    ${FW}/components/measure/buttons.c
    ${FW}/components/measure/hid_keymap.c
    ${FW}/components/sensor_mag/as5311_proto.c
    ${FW}/components/sensor_cap/cap_demod.c
)
target_include_directories(caliper_tests PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
    ${FW}/main/proto
    ${FW}/components/measure/include
    ${FW}/components/sensor_mag/include
    ${FW}/components/sensor_cap/include
)
target_compile_options(caliper_tests PRIVATE -Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion
    -fsanitize=address,undefined -fno-omit-frame-pointer -O1 -g)
target_link_options(caliper_tests PRIVATE -fsanitize=address,undefined)
target_link_libraries(caliper_tests PRIVATE m)

enable_testing()
add_test(NAME caliper_tests COMMAND caliper_tests)
