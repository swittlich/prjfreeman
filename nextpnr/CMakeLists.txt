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

# Datenquellen des Generators in arch/xc2064 (über den Symlink in upstream/nextpnr aufgelöst): das Paket
# xc2064db und Shirriffs Dateien im Submodule external/shirriff-xc2064. Ändert sich eine davon, entsteht
# die Chipdb neu.
get_filename_component(XC2064_NEXTPNR_DIR ${CMAKE_CURRENT_SOURCE_DIR} REALPATH)
get_filename_component(XC2064_ARCH_DIR ${XC2064_NEXTPNR_DIR} DIRECTORY)
file(GLOB XC2064_DB_SOURCES CONFIGURE_DEPENDS ${XC2064_ARCH_DIR}/xc2064db/*.py)
set(XC2064_DATA
    ${XC2064_ARCH_DIR}/external/shirriff-xc2064/html/XC2064-def.txt
    ${XC2064_ARCH_DIR}/external/shirriff-xc2064/html/draw.js
    ${XC2064_ARCH_DIR}/external/shirriff-xc2064/html/clb.js
    ${XC2064_ARCH_DIR}/external/shirriff-xc2064/html/iob.js
)

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
            ${XC2064_DB_SOURCES}
            ${XC2064_DATA}
    )

    add_bba_compile_command(
        TARGET  nextpnr-himbaechel-xc2064-chipdb
        OUTPUT  himbaechel/xc2064/chipdb-${device}.bin
        INPUT   ${CMAKE_CURRENT_BINARY_DIR}/chipdb-${device}.bba
        MODE    binary
    )
endforeach()
