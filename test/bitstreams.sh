#!/usr/bin/env bash
# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
# Test of the bitstream tools with real bitstreams from Xilinx's XACT: the references from openxc2064
# (bitstream/XACT_comparisons, hardware/bitstreams/AND_OR.BIT) and Shirriff's TEST1.RBT.
#   test/bitstreams.sh [file.BIT|file.RBT ...]
# Checks:
#   - python3 -m xc2064db: cross-checks of the data sources (bit map, lines, switch matrices, CLB muxes)
#   - xc2064unpack per bitstream: every programmed bit and every mux code is in the bit map
#   - round trip: xc2064pack turns the text back into a bitstream that is bit-identical to the original
#   - xc2064shirriff: Shirriff's decoder (JavaScript in QuickJS) decodes every bitstream like the package
#     (only with the Python package quickjs)
# Afterwards the text files are in build/flows/xc2064/test/bitstreams/.
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

log "Cross-checks of the data sources (python3 -m xc2064db)"
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
	printf '  %-14s %s\n' "$name" "$(grep -m1 '^xc2064unpack: .*problems' "$OUT/${name%.*}.log" | sed 's/^xc2064unpack: [^:]*: //')"
	if [[ $rc -ne 0 ]]; then
		grep -v ' problems$' "$OUT/${name%.*}.log" | head -5 | sed 's/^/    /'
		failed=$((failed + 1))
		continue
	fi
	# Round trip: text -> RBT, bit-identical to the original?
	rc=0
	python3 "$ARCH/tools/xc2064pack" "$OUT/${name%.*}.txt" -o "$OUT/${name%.*}.rt.rbt" --compare "$f" \
		2>>"$OUT/${name%.*}.log" || rc=$?
	printf '  %-14s round trip with xc2064pack: %s\n' "" "$(grep -m1 'comparison with' "$OUT/${name%.*}.log" | sed 's/^.*: //')"
	if [[ $rc -ne 0 ]]; then
		tail -2 "$OUT/${name%.*}.log" | sed 's/^/    /'
		failed=$((failed + 1))
	fi
done

if python3 -c "import quickjs" 2>/dev/null; then
	log "Cross-check with Shirriff's decoder (xc2064shirriff)"
	rc=0
	python3 "$ARCH/tools/xc2064shirriff" "${files[@]}" 2>"$OUT/shirriff.log" || rc=$?
	sed 's/^xc2064shirriff: /  /' "$OUT/shirriff.log"
	[[ $rc -eq 0 ]] || failed=$((failed + 1))
else
	warn "Python package quickjs missing: no cross-check with Shirriff's decoder (pip install quickjs)"
fi

log "${#files[@]} bitstreams, $failed errors. Text files: $OUT"
[[ $failed -eq 0 ]]
