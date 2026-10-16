set(SOURCES
    constids.inc
    xc2064.cc
    gfxids.inc
)

add_nextpnr_himbaechel_microarchitecture(${uarch}
    CORE_SOURCES ${SOURCES}
)

set(ALL_HIMBAECHEL_XC2064_DEVICES xc2064)
set(HIMBAECHEL_XC2064_DEVICES ${ALL_HIMBAECHEL_XC2064_DEVICES} CACHE STRING
    "Include support for these Xc2064 devices (available: ${ALL_HIMBAECHEL_XC2064_DEVICES})")
message(STATUS "Enabled Himbaechel-Xc2064 devices: ${HIMBAECHEL_XC2064_DEVICES}")

foreach (device ${HIMBAECHEL_XC2064_DEVICES})
    if (NOT device IN_LIST ALL_HIMBAECHEL_XC2064_DEVICES)
        message(FATAL_ERROR "Device ${device} is not a supported Xc2064 device")
    endif()

    add_bba_produce_command(
        TARGET  nextpnr-himbaechel-xc2064-bba
        COMMAND ${CMAKE_COMMAND} -E env PYTHONPATH=${CMAKE_SOURCE_DIR}/himbaechel ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/xc2064_arch_gen.py
            ${CMAKE_CURRENT_BINARY_DIR}/chipdb-${device}.bba.new
        OUTPUT
            ${CMAKE_CURRENT_BINARY_DIR}/chipdb-${device}.bba
        INPUTS
            ${CMAKE_CURRENT_SOURCE_DIR}/xc2064_arch_gen.py
            ${CMAKE_CURRENT_SOURCE_DIR}/constids.inc
            ${CMAKE_CURRENT_SOURCE_DIR}/gfxids.inc
    )

    add_bba_compile_command(
        TARGET  nextpnr-himbaechel-xc2064-chipdb
        OUTPUT  himbaechel/xc2064/chipdb-${device}.bin
        INPUT   ${CMAKE_CURRENT_BINARY_DIR}/chipdb-${device}.bba
        MODE    binary
    )
endforeach()
