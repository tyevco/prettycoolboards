# PrettyCool Caliper firmware (ESP-IDF >= 5.4, target esp32s3)
#   idf.py set-target esp32s3 && idf.py build
# 8 MB module (N8R2):
#   idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.8mb" set-target esp32s3 build
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/components)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(caliper)
