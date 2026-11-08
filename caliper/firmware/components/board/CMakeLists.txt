# "board": exposes the generated pin header (main/board_pins.h) and the GATT contract header
# (main/proto/caliper_gatt.h) to all components, and checks that the pin header matches
# caliper/hardware/design/nets.py so the pin map cannot drift.
set(fw_dir ${CMAKE_CURRENT_LIST_DIR}/../..)

idf_component_register(INCLUDE_DIRS "${fw_dir}/main" "${fw_dir}/main/proto")

set(nets_py ${fw_dir}/../hardware/design/nets.py)
if(CMAKE_BUILD_EARLY_EXPANSION)
    # requirements-expansion pass: nothing to check yet
elseif(EXISTS ${nets_py})
    idf_build_get_property(python PYTHON)
    execute_process(
        COMMAND ${python} ${fw_dir}/tools/gen_pins.py --check
        RESULT_VARIABLE pins_rc
        OUTPUT_VARIABLE pins_out
        ERROR_VARIABLE pins_err)
    if(NOT pins_rc EQUAL 0)
        message(FATAL_ERROR "board_pins.h does not match nets.py: ${pins_err}"
                            "Regenerate with: python ${fw_dir}/tools/gen_pins.py")
    endif()
    # re-run the check when nets.py changes
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${nets_py} ${fw_dir}/tools/gen_pins.py)
else()
    message(WARNING "nets.py not found; using the committed board_pins.h unchecked")
endif()
