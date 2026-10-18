#!/usr/bin/env bash
# Test der Bitstream-Werkzeuge mit echten Bitstreams aus Xilinx' XACT: die Referenzen aus openxc2064
# (bitstream/XACT_comparisons, hardware/bitstreams/AND_OR.BIT) und Shirriffs TEST1.RBT.
#   test/bitstreams.sh [datei.BIT|datei.RBT ...]
# Prüft:
#   - python3 -m xc2064db: Gegenproben der Datenquellen (Bitkarte, Leitungen, Switch-Matrizen, CLB-Muxe)
#   - xc2064unpack je Bitstream: jedes programmierte Bit und jeder Mux-Code steht in der Bitkarte
#   - Rundlauf: xc2064pack macht aus dem Text wieder einen Bitstream, der bitgenau dem Original gleicht
#   - xc2064shirriff: Shirriffs Decoder (JavaScript in QuickJS) dekodiert jeden Bitstream wie das Paket
#     (nur mit dem Python-Paket quickjs)
# Die Textdateien liegen danach unter build/flows/xc2064/test/bitstreams/.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCH="$(dirname "$HERE")"
source "$ARCH/../../scripts/lib.sh"

OUT="$FAT_BUILD/flows/xc2064/test/bitstreams"
files=("$@")
if [[ ${#files[@]} -eq 0 ]]; then
	files=("$ARCH"/external/openxc2064/bitstream/XACT_comparisons/*.BIT "$ARCH"/external/openxc2064/hardware/bitstreams/AND_OR.BIT
		"$ARCH"/external/shirriff-xc2064/obsolete/test/TEST1.RBT)
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
		continue
	fi
	# Rundlauf: Text -> RBT, bitgenau gleich dem Original?
	rc=0
	python3 "$ARCH/tools/xc2064pack" "$OUT/${name%.*}.txt" -o "$OUT/${name%.*}.rt.rbt" --compare "$f" \
		2>>"$OUT/${name%.*}.log" || rc=$?
	printf '  %-14s Rundlauf mit xc2064pack: %s\n' "" "$(grep -m1 'Vergleich mit' "$OUT/${name%.*}.log" | sed 's/^.*: //')"
	if [[ $rc -ne 0 ]]; then
		tail -2 "$OUT/${name%.*}.log" | sed 's/^/    /'
		failed=$((failed + 1))
	fi
done

if python3 -c "import quickjs" 2>/dev/null; then
	log "Gegenprobe mit Shirriffs Decoder (xc2064shirriff)"
	rc=0
	python3 "$ARCH/tools/xc2064shirriff" "${files[@]}" 2>"$OUT/shirriff.log" || rc=$?
	sed 's/^xc2064shirriff: /  /' "$OUT/shirriff.log"
	[[ $rc -eq 0 ]] || failed=$((failed + 1))
else
	warn "Python-Paket quickjs fehlt: keine Gegenprobe mit Shirriffs Decoder (pip install quickjs)"
fi

log "${#files[@]} Bitstreams, $failed Fehler. Textdateien: $OUT"
[[ $failed -eq 0 ]]
