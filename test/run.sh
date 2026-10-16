#!/usr/bin/env bash
# Regressionstest für xc2064: Synthese, Place & Route über mehrere Seeds (mit und ohne PCF) und ein
# formaler Vergleich jedes Ergebnisses mit dem RTL.
#   test/run.sh [design.v ...]          ohne Argument alle examples/*.v
# Spalten je Lauf:
#   PnR    nextpnr endet ohne Fehler innerhalb von TIMEOUT Sekunden (router2 hat kein Abbruchlimit)
#   Netz   die Netzliste nach dem Routing (*.pnr.json, also nach pack()) ist äquivalent zum RTL, mit
#          Tristate auch im hochohmigen Zustand und auf dem Lesepfad von inout (tristate_split.py)
#   Pips   die nur aus Bels und benutzten Pips zurückgewonnene Netzliste (extract_netlist.py) ist stimmig
#          und äquivalent zum RTL. Das deckt Platzierung und Routing mit ab
#   Fmax   kleinste Frequenz aller Takte nach dem Routing, mit FMIN=… (MHz) ist ein Wert darunter ein Fehler
#   Routing  Iterationen und Laufzeit von router2 (nur Information)
# Umgebungsvariablen: SEEDS="1 2 3 4 5 6" (zusätzlich zum nextpnr-Standard), FREQ=5, FMIN=…, TIMEOUT=300,
# YOSYS=…, NEXTPNR=…
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCH="$(dirname "$HERE")"
source "$ARCH/../../scripts/lib.sh"

YOSYS="${YOSYS:-yosys}"
NEXTPNR="${NEXTPNR:-nextpnr-himbaechel}"
SEEDS="${SEEDS-1 2 3 4 5 6}"
TIMEOUT="${TIMEOUT:-300}"
OUT="$FAT_BUILD/flows/xc2064/test"
designs=("$@")
[[ ${#designs[@]} -eq 0 ]] && designs=("$ARCH"/examples/*.v)

# Formaler Vergleich in drei Schritten, alle Netzlisten flach als yosys-JSON:
# gold_json <RTL> <aus.json>: das RTL, Tristate wie in synth_xc2064 (tribuf -logic, deminout)
gold_json() {
	"$YOSYS" -q -l "${2%.json}.log" -p "
		read_verilog $1
		prep -auto-top -flatten
		tribuf -logic
		deminout
		splitnets
		opt_clean
		write_json $2" >/dev/null 2>&1
}
# gate_json <yosys-Befehl zum Lesen der Netzliste> <aus.json>: mit den Modellen der Primitive
gate_json() {
	"$YOSYS" -q -l "${2%.json}.log" -p "
		$1
		read_verilog $ARCH/yosys/cells_sim.v $HERE/pnr_cells.v
		hierarchy -auto-top
		proc
		flatten
		tribuf -logic
		opt_clean
		write_json $2" >/dev/null 2>&1
}
# equiv <gold.json> <gate.json>: Induktion über die gleichnamigen Register, Takte über clk2fflogic mit
# ihrer Flanke. Mit Tristate zweimal, hochohmig als 0 und als 1, inout-Ports aufgetrennt
# (tristate_split.py).
equiv() {
	local z n
	for z in 0 1; do
		n="$(python3 "$HERE/tristate_split.py" "$1" "${1%.json}-z$z.json" $z)" || return 1
		python3 "$HERE/tristate_split.py" "$2" "${2%.json}-z$z.json" $z >/dev/null || return 1
		"$YOSYS" -q -l "${2%.json}-z$z.equiv.log" -p "
			read_json ${1%.json}-z$z.json
			rename -top gold
			design -stash gold
			read_json ${2%.json}-z$z.json
			rename -top gate
			design -stash gate
			design -copy-from gold -as gold gold
			design -copy-from gate -as gate gate
			equiv_make gold gate equiv
			hierarchy -top equiv
			clk2fflogic
			opt_clean
			equiv_simple -seq 5
			equiv_induct -seq 5
			equiv_status -assert" >/dev/null 2>&1 || return 1
		[[ $n -gt 0 ]] || break # ohne Tristate reicht ein Lauf
	done
}

# kleinste "Max frequency" je Takt aus dem letzten Bericht im Log
fmax() {
	awk -v q="'" '/Max frequency for clock/ { split($0, a, q); v = a[3]; sub(/^: /, "", v); sub(/ MHz.*/, "", v); last[a[2]] = v }
		END { for (c in last) if (m == "" || last[c] + 0 < m + 0) m = last[c]; print m }' "$1"
}

make -s -C "$ARCH/yosys"
mkdir -p "$OUT"
runs=0
failed=0
row() { printf '%-10s %-5s %-8s %-8s %-6s %-6s %-11s %s\n' "$@"; }
row Design PCF Seed PnR Netz Pips Fmax Routing

for d in "${designs[@]}"; do
	d="$(realpath "$d")"
	name="$(basename "${d%.v}")"
	dir="$OUT/$name"
	mkdir -p "$dir"
	if ! "$YOSYS" -q -l "$dir/yosys.log" -m "$ARCH/yosys/build/xc2064.so" -p "synth_xc2064 -json $dir/$name.json" \
		"$d" >/dev/null 2>&1; then
		row "$name" - - "Synthese fehlgeschlagen ($dir/yosys.log)"
		runs=$((runs + 1))
		failed=$((failed + 1))
		continue
	fi
	gold="$dir/gold.json"
	if ! gold_json "$d" "$gold"; then
		row "$name" - - "RTL für den Vergleich nicht lesbar (${gold%.json}.log)"
		runs=$((runs + 1))
		failed=$((failed + 1))
		continue
	fi
	pcf="${d%.v}.pcf"
	modes=(ohne)
	[[ -f "$pcf" ]] && modes=(mit ohne)
	for m in "${modes[@]}"; do
		for s in default $SEEDS; do
			run="$dir/pcf-$m-seed-$s"
			opts=()
			[[ $m == mit ]] && opts+=(--vopt "pcf=$pcf")
			[[ $s != default ]] && opts+=(--seed "$s")
			rm -f "$run".*
			rc=0
			XC2064_EXTRACT="$run.extracted.v" timeout "$TIMEOUT" "$NEXTPNR" --device XC2064 --json "$dir/$name.json" \
				--write "$run.pnr.json" -l "$run.nextpnr.log" --freq "${FREQ:-5}" --timing-allow-fail \
				--post-route "$HERE/extract_netlist.py" "${opts[@]}" >"$run.out" 2>&1 || rc=$?
			pnr=ok net=- pips=- f=
			if [[ $rc -eq 124 ]]; then
				pnr=Timeout
			elif [[ $rc -ne 0 ]]; then
				pnr=Fehler
			else
				f="$(fmax "$run.nextpnr.log")"
				net=ok
				{ gate_json "read_json $run.pnr.json" "$run.netz.json" && equiv "$gold" "$run.netz.json"; } || net=FEHLER
				pips=ok
				grep -q "^XC2064_EXTRACT: .* 0 Fehler$" "$run.out" || pips=FEHLER
				[[ $pips == ok ]] && {
					{ gate_json "read_verilog $run.extracted.v" "$run.pips.json" && equiv "$gold" "$run.pips.json"; } ||
						pips=FEHLER
				}
			fi
			bad=0
			[[ $pnr == ok && $net == ok && $pips == ok ]] || bad=1
			if [[ -n "${FMIN:-}" && -n "$f" ]] && awk -v f="$f" -v m="$FMIN" 'BEGIN { exit !(f < m) }'; then
				f="$f<$FMIN"
				bad=1
			fi
			# router2: Iterationen und Zeit (viele Iterationen = Netze wechseln sich an einem Draht ab)
			it="$(grep -o 'iter=[0-9]*' "$run.nextpnr.log" 2>/dev/null | tail -1 | cut -d= -f2 || true)"
			t="$(grep -o 'Router2 time [0-9.]*' "$run.nextpnr.log" 2>/dev/null | awk '{ printf "%.0f", $3 }' || true)"
			row "$name" "$m" "$s" "$pnr" "$net" "$pips" "${f:+$f MHz}" "${it:+$it It. ${t:-?} s}"
			runs=$((runs + 1))
			failed=$((failed + bad))
		done
	done
done

log "$runs Läufe, $failed fehlgeschlagen. Logs: $OUT"
[[ $failed -eq 0 ]]
