#!/usr/bin/env bash
# Kompletter Flow für xc2064: yosys (synth_xc2064) -> nextpnr-himbaechel --device XC2064
#   flow.sh [design.v] [weitere nextpnr-Optionen, z.B. --gui]
# Pins: design.pcf neben design.v (set_io <Port> <Pin>) wird automatisch verwendet.
# Umgebungsvariablen: YOSYS=..., NEXTPNR=... (z.B. Debug-Binaries aus build/*-debug), PCF=... (andere
# PCF-Datei)
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
BASE="$OUT/$(basename "${DESIGN%.v}")"
mkdir -p "$OUT"

log "Baue yosys-Plugin"
make -s -C "$HERE/yosys"

log "Synthese: $DESIGN"
"$YOSYS" -q -l "$BASE.yosys.log" -m "$HERE/yosys/build/xc2064.so" \
	-p "synth_xc2064 -json $BASE.json" "$DESIGN"

# Timing-Ziel: zeitgemäße Taktfrequenz (MHz). Ein 16-Bit-Zähler ohne Carry-Logik schafft ~6 MHz.
log "Place & Route: nextpnr-himbaechel --device XC2064 --freq ${FREQ:-5} ${PCF_OPT[*]}"
"$NEXTPNR" --device XC2064 --json "$BASE.json" --write "$BASE.pnr.json" -l "$BASE.nextpnr.log" \
	--freq "${FREQ:-5}" "${PCF_OPT[@]}" "$@"

log "Ergebnisse: $OUT"
