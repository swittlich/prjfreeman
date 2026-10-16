# Baut das Yosys-Plugin der Architektur xc2064.
#   make                                  -> build/xc2064.so gegen yosys-config im PATH (build/install)
#   make YOSYS_CONFIG=<yosys-build>/yosys-config BUILD=build-debug
#                                         -> gegen einen bestimmten yosys-Build (z.B. zum Debuggen)
# Das Plugin muss mit demselben yosys gebaut werden, der es lädt.

YOSYS_CONFIG ?= yosys-config
BUILD        ?= build
NAME         := xc2064
SRCS         := synth_$(NAME).cc
EXTRA_FLAGS  ?= -ggdb -O0
# Neu bauen, wenn ein anderes yosys installiert wurde (z.B. mit pyosys: andere Struktur-Layouts)
YOSYS_HDRS   := $(wildcard $(shell $(YOSYS_CONFIG) --datdir 2>/dev/null)/include/kernel/*.h)

.PHONY: all clean

all: $(BUILD)/$(NAME).so

$(BUILD)/$(NAME).so: $(SRCS) $(YOSYS_HDRS) | $(BUILD)
	$(YOSYS_CONFIG) --build $@ $(SRCS) $(EXTRA_FLAGS) -DFAT_ARCH_DATDIR='"$(CURDIR)"'

$(BUILD):
	mkdir -p $@

clean:
	rm -rf build build-debug
