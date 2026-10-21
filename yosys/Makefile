# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
# Builds the Yosys plugin of the xc2064 architecture.
#   make                                  -> build/xc2064.so against the yosys-config in PATH (build/install)
#   make YOSYS_CONFIG=<yosys-build>/yosys-config BUILD=build-debug
#                                         -> against a specific yosys build (e.g. for debugging)
# The plugin must be built with the same yosys that loads it.

YOSYS_CONFIG ?= yosys-config
BUILD        ?= build
NAME         := xc2064
SRCS         := synth_$(NAME).cc
EXTRA_FLAGS  ?= -ggdb -O0
# Rebuild when a different yosys has been installed (e.g. with pyosys: different struct layouts)
YOSYS_HDRS   := $(wildcard $(shell $(YOSYS_CONFIG) --datdir 2>/dev/null)/include/kernel/*.h)

.PHONY: all clean

all: $(BUILD)/$(NAME).so

$(BUILD)/$(NAME).so: $(SRCS) $(YOSYS_HDRS) | $(BUILD)
	$(YOSYS_CONFIG) --build $@ $(SRCS) $(EXTRA_FLAGS) -DFAT_ARCH_DATDIR='"$(CURDIR)"'

$(BUILD):
	mkdir -p $@

clean:
	rm -rf build build-debug
