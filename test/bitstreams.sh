#!/usr/bin/env bash
# Test der Bitstream-Werkzeuge mit echten Bitstreams aus Xilinx' XACT: die Referenzen aus openxc2064
# (bitstream/XACT_comparisons, hardware/bitstreams/AND_OR.BIT) und Shirriffs TEST1.RBT.
#   test/bitstreams.sh [datei.BIT|datei.RBT ...]
# Prüft:
#   - python3 -m xc2064db: Gegenproben der Datenquellen (Bitkarte, Leitungen, Switch-Matrizen, CLB-Muxe)
#   - xc2064unpack je Bitstream: jedes programmierte Bit und jeder Mux-Code steht in der Bitkarte
# Die Textdateien liegen danach unter build/flows/xc2064/test/bitstreams/.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCH="$(dirname "$HERE")"
source "$ARCH/../../scripts/lib.sh"

OUT="$FAT_BUILD/flows/xc2064/test/bitstreams"
files=("$@")
if [[ ${#files[@]} -eq 0 ]]; then
	files=("$ARCH"/openxc2064/bitstream/XACT_comparisons/*.BIT "$ARCH"/openxc2064/hardware/bitstreams/AND_OR.BIT
		"$ARCH"/shirriff-xc2064/obsolete/test/TEST1.RBT)
fi
mkdir -p "$OUT"
failed=0

log "Gegenproben der Datenquellen (python3 -m xc2064db)"
if ! (cd "$ARCH" && python3 -m xc2064db >"$OUT/xc2064db.log" 2>&1); then
	cat "$OUT/xc2064db.log"
	failed=$((failed + 1))
else
	grep -E "^\s+\[" "$OUT/xc2064db.log" | sed 's/^ */  /'
fi

log "xc2064unpack"
for f in "${files[@]}"; do
	name="$(basename "$f")"
	rc=0
	python3 "$ARCH/tools/xc2064unpack" "$f" -o "$OUT/${name%.*}.txt" 2>"$OUT/${name%.*}.log" || rc=$?
	printf '  %-14s %s\n' "$name" "$(grep -m1 '^xc2064unpack: .*Probleme' "$OUT/${name%.*}.log" | sed 's/^xc2064unpack: [^:]*: //')"
	if [[ $rc -ne 0 ]]; then
		grep -v ' Probleme$' "$OUT/${name%.*}.log" | head -5 | sed 's/^/    /'
		failed=$((failed + 1))
	fi
done

log "${#files[@]} Bitstreams, $failed Fehler. Textdateien: $OUT"
[[ $failed -eq 0 ]]
