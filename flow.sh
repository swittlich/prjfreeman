#!/usr/bin/env bash
# Complete flow for xc2064: yosys (synth_xc2064) -> nextpnr-himbaechel --device XC2064
#   flow.sh [design.v] [further nextpnr options, e.g. --gui]
# Pins: design.pcf next to design.v (set_io <port> <pin>) is used automatically.
# Environment variables: YOSYS=..., NEXTPNR=... (e.g. debug binaries from build/*-debug), PCF=... (other
# PCF file), SEED=... (seed for nextpnr, without SEED the nextpnr default), FREQ=... (timing target in
# MHz, default 5)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../../scripts/lib.sh"

DESIGN="$HERE/examples/blinky.v"
if [[ $# -gt 0 && "$1" == *.v ]]; then
	DESIGN="$(realpath "$1")"
	shift
fi
YOSYS="${YOSYS:-yosys}"
NEXTPNR="${NEXTPNR:-nextpnr-himbaechel}"
OUT="$FAT_BUILD/flows/xc2064"
PCF="${PCF:-${DESIGN%.v}.pcf}"
PCF_OPT=()
[[ -f "$PCF" ]] && PCF_OPT=(--vopt "pcf=$PCF")
# Seed: without SEED the nextpnr default, SEED=n passes --seed n. A --seed in the passed-through
# options takes precedence (nextpnr rejects a duplicate --seed).
SEED_OPT=()
[[ -n "${SEED:-}" ]] && SEED_OPT=(--seed "$SEED")
for a in "$@"; do [[ "$a" == --seed || "$a" == --seed=* ]] && SEED_OPT=(); done
BASE="$OUT/$(basename "${DESIGN%.v}")"
mkdir -p "$OUT"

log "Building yosys plugin"
make -s -C "$HERE/yosys"

log "Synthesis: $DESIGN"
"$YOSYS" -q -l "$BASE.yosys.log" -m "$HERE/yosys/build/xc2064.so" \
	-p "synth_xc2064 -json $BASE.json" "$DESIGN"

# Timing target: a period-appropriate clock frequency (MHz). A 16-bit counter without carry logic reaches ~6 MHz.
log "Place & Route: nextpnr-himbaechel --device XC2064 --freq ${FREQ:-5} ${SEED_OPT[*]} ${PCF_OPT[*]}"
"$NEXTPNR" --device XC2064 --json "$BASE.json" --write "$BASE.pnr.json" -l "$BASE.nextpnr.log" \
	--freq "${FREQ:-5}" "${SEED_OPT[@]}" "${PCF_OPT[@]}" "$@"

log "Results: $OUT"
