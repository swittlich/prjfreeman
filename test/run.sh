#!/usr/bin/env bash
# Regression test for xc2064: synthesis, place & route over several seeds (with and without PCF) and a
# formal comparison of every result with the RTL.
#   test/run.sh [design.v ...]          without arguments all examples/*.v
# Lines "// expected: <cell type> <count>" in the design check the synthesis (e.g. XC2000_FGM in shiftreg.v).
# Columns per run:
#   PnR    nextpnr finishes without errors within TIMEOUT seconds (router2 has no abort limit)
#   Net    the netlist after routing (*.pnr.json, i.e. after pack()) is equivalent to the RTL, with
#          tristate also in the high-impedance state and on the read path of inout (tristate_split.py)
#   Pips   the netlist recovered solely from Bels and used Pips (extract_netlist.py) is consistent
#          and equivalent to the RTL. This also covers placement and routing
#   Bitstream  round trip through the bitstream: nextpnr writes the configuration as text (--vopt out=),
#          xc2064pack turns it into an RBT file, xc2064unpack and xc2064pack reproduce it bit-exactly,
#          and the netlist recovered from the bitstream alone (xc2064netlist) is equivalent to the RTL
#   Shirriff  independent cross-check: Shirriff's decoder (xc2064shirriff, JavaScript in QuickJS) reads the
#          RBT file itself and decodes CLBs, muxes, IOBs, Pips and switch matrices like the package
#          (- without the Python package quickjs)
#   LCA    xc2064lca writes the configuration as an LCA for MAKEBITS whose blocks and nets match the bitstream
#          (check_xact.py; MAKEBITS itself runs only in DOSBox, outside the test)
#   Fmax   lowest frequency of all clocks after routing; with FMIN=… (MHz) a value below it is an error
#   Routing  iterations and run time of router2 (information only)
# In addition, per design one run without PCF in every other package (column PCF: PD48, PC44, PG68) and one run
# each with and without PCF without the clock buffers (--vopt noclkbuf, column Seed: noclkbuf). Bitstream also
# requires that the configuration uses a clock buffer, and none with noclkbuf.
# Then per design the XNF netlist for XACT (xc2064xnf) from gates, with --lut and with --iobff, checked
# with check_xact.py (structure, drivers, pads, storage elements and pads as in synth_xc2064, LOC from the PCF).
# Environment variables: SEEDS="1 2 3 4 5 6" (in addition to the nextpnr default), PACKAGES="PD48 PC44 PG68",
# FREQ=5, FMIN=…, TIMEOUT=300, YOSYS=…, NEXTPNR=…, TEST_JOBS (parallel runs, default JOBS, at most 10)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCH="$(dirname "$HERE")"
source "$ARCH/../../scripts/lib.sh"

YOSYS="${YOSYS:-yosys}"
NEXTPNR="${NEXTPNR:-nextpnr-himbaechel}"
SEEDS="${SEEDS-1 2 3 4 5 6}"
PACKAGES="${PACKAGES-PD48 PC44 PG68}"
TIMEOUT="${TIMEOUT:-300}"
OUT="$FAT_BUILD/flows/xc2064/test"
designs=("$@")
[[ ${#designs[@]} -eq 0 ]] && designs=("$ARCH"/examples/*.v)

# Formal comparison in three steps, all netlists flat as yosys JSON:
# gold_json <RTL> <out.json>: the RTL, tristate as in synth_xc2064 (tribuf -logic, deminout)
gold_json() {
	# proc -norom: large case statements (7-segment decoder) stay logic; equiv cannot compute with a ROM
	"$YOSYS" -q -l "${2%.json}.log" -p "
		read_verilog $1
		proc -norom
		prep -auto-top -flatten
		tribuf -logic
		deminout
		splitnets
		opt_clean
		write_json $2" >/dev/null 2>&1
}
# gate_json <yosys command to read the netlist> <out.json>: with the models of the primitives
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
# equiv <gold.json> <gate.json>: induction over the registers of the same name, clocks via clk2fflogic with
# their edge. With tristate twice, high-impedance as 0 and as 1, inout ports split
# (tristate_split.py).
# gold_split <gold.json>: the two variants of the RTL, once per design (the runs execute in parallel)
gold_split() {
	local z n
	for z in 0 1; do
		n="$(python3 "$HERE/tristate_split.py" "$1" "${1%.json}-z$z.json" $z)" || return 1
	done
	echo "$n" >"${1%.json}.ntri"
}
equiv() {
	local z n
	[[ -f "${1%.json}.ntri" ]] || gold_split "$1" || return 1
	n="$(cat "${1%.json}.ntri")"
	for z in 0 1; do
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
		[[ $n -gt 0 ]] || break # without tristate one run is enough
	done
}

# lowest "Max frequency" per clock from the last report in the log
fmax() {
	awk -v q="'" '/Max frequency for clock/ { split($0, a, q); v = a[3]; sub(/^: /, "", v); sub(/ MHz.*/, "", v); last[a[2]] = v }
		END { for (c in last) if (m == "" || last[c] + 0 < m + 0) m = last[c]; print m }' "$1"
}

make -s -C "$ARCH/yosys"
mkdir -p "$OUT"
runs=0
failed=0
row() { printf '%-10s %-7s %-8s %-8s %-6s %-6s %-10s %-9s %-6s %-11s %s\n' "$@"; }
# Shirriff's decoder needs the Python package quickjs; without it the column stays empty (-)
SHIRRIFF=1
python3 -c "import quickjs" 2>/dev/null || {
	SHIRRIFF=0
	warn "Python package quickjs missing: no cross-check with Shirriff's decoder (pip install quickjs)"
}
row Design PCF Seed PnR Net Pips Bitstream Shirriff LCA Fmax Routing
# bitstream <run>: text -> RBT -> (unpack -> pack bit-exact) -> netlist -> comparison with the RTL
bitstream() {
	local t="$ARCH/tools"
	python3 "$t/xc2064pack" "$1.cfg.txt" -o "$1.rbt" 2>"$1.bitstream.log" &&
		python3 "$t/xc2064unpack" "$1.rbt" -o "$1.unpacked.txt" 2>>"$1.bitstream.log" &&
		python3 "$t/xc2064pack" "$1.unpacked.txt" -o "$1.rt.rbt" --compare "$1.rbt" 2>>"$1.bitstream.log" &&
		python3 "$t/xc2064netlist" "$1.rbt" --meta "$1.cfg.txt" -o "$1.bit.v" 2>>"$1.bitstream.log" &&
		gate_json "read_verilog $1.bit.v" "$1.bit.json" && equiv "$gold" "$1.bit.json"
}

# pnr_run <run> <PCF column> <Seed column> <nextpnr options...>: one run with all checks, one row
pnr_run() {
	local run="$1" m="$2" s="$3"
	shift 3
	rm -f "$run".*
	local rc=0
	XC2064_EXTRACT="$run.extracted.v" timeout "$TIMEOUT" "$NEXTPNR" --device XC2064 --json "$dir/$name.json" \
		--write "$run.pnr.json" -l "$run.nextpnr.log" --freq "${FREQ:-5}" --timing-allow-fail \
		--vopt "out=$run.cfg.txt" --post-route "$HERE/extract_netlist.py" "$@" >"$run.out" 2>&1 || rc=$?
	local pnr=ok net=- pips=- bit=- shir=- lca=- f=
	if [[ $rc -eq 124 ]]; then
		pnr=Timeout
	elif [[ $rc -ne 0 ]]; then
		pnr=error
	else
		f="$(fmax "$run.nextpnr.log")"
		net=ok
		{ gate_json "read_json $run.pnr.json" "$run.net.json" && equiv "$gold" "$run.net.json"; } || net=FAIL
		pips=ok
		grep -q "^XC2064_EXTRACT: .* 0 errors$" "$run.out" || pips=FAIL
		[[ $pips == ok ]] && {
			{ gate_json "read_verilog $run.extracted.v" "$run.pips.json" && equiv "$gold" "$run.pips.json"; } ||
				pips=FAIL
		}
		bit=ok
		bitstream "$run" || bit=FAIL
		# clock buffer: used (every example has a clock from a pad), none with --vopt noclkbuf
		if grep -q '^mux CLK\.\(AA\|II\)\.I ' "$run.cfg.txt"; then
			[[ $s != noclkbuf ]] || bit=FAIL
		else
			[[ $s == noclkbuf ]] || bit=FAIL
		fi
		if [[ $SHIRRIFF -eq 1 && -f "$run.rbt" ]]; then
			shir=ok
			python3 "$ARCH/tools/xc2064shirriff" "$run.rbt" 2>"$run.shirriff.log" || shir=FAIL
		fi
		# LCA for MAKEBITS: blocks and nets as in the bitstream
		if [[ -f "$run.rbt" ]]; then
			lca=ok
			{ python3 "$ARCH/tools/xc2064lca" "$run.cfg.txt" -o "$run.lca" &&
				python3 "$HERE/check_xact.py" lca "$run.lca" "$run.cfg.txt" "$run.rbt"; } >"$run.lca.log" 2>&1 ||
				lca=FAIL
		fi
	fi
	local bad=0
	[[ $pnr == ok && $net == ok && $pips == ok && $bit == ok && $shir != FAIL && $lca != FAIL ]] || bad=1
	if [[ -n "${FMIN:-}" && -n "$f" ]] && awk -v f="$f" -v m="$FMIN" 'BEGIN { exit !(f < m) }'; then
		f="$f<$FMIN"
		bad=1
	fi
	# router2: iterations and time (many iterations = nets take turns on a wire)
	local it t
	it="$(grep -o 'iter=[0-9]*' "$run.nextpnr.log" 2>/dev/null | tail -1 | cut -d= -f2 || true)"
	t="$(grep -o 'Router2 time [0-9.]*' "$run.nextpnr.log" 2>/dev/null | awk '{ printf "%.0f", $3 }' || true)"
	row "$name" "$m" "$s" "$pnr" "$net" "$pips" "$bit" "$shir" "$lca" "${f:+$f MHz}" "${it:+$it it. ${t:-?} s}"
	echo "$bad" >"$run.bad"
}

# Queue of the runs (per run: design directory, name, gold, run, columns, options separated by \x1f)
q_dir=() q_name=() q_gold=() q_run=() q_m=() q_s=() q_opts=()
xnf_d=() # designs for the XNF check (synthesis passed)
queue() {
	q_dir+=("$dir") q_name+=("$name") q_gold+=("$gold") q_run+=("$1") q_m+=("$2") q_s+=("$3")
	shift 3
	local IFS=$'\x1f'
	q_opts+=("$*")
}

for d in "${designs[@]}"; do
	d="$(realpath "$d")"
	name="$(basename "${d%.v}")"
	dir="$OUT/$name"
	mkdir -p "$dir"
	if ! "$YOSYS" -q -l "$dir/yosys.log" -m "$ARCH/yosys/build/xc2064.so" -p "synth_xc2064 -json $dir/$name.json" \
		"$d" >/dev/null 2>&1; then
		row "$name" - - "synthesis failed ($dir/yosys.log)"
		runs=$((runs + 1))
		failed=$((failed + 1))
		continue
	fi
	# expected cell counts (statistics at the end of synth_xc2064)
	wrong=""
	while read -r typ n; do
		got="$(awk -v t="$typ" '$2 == t { c = $1 } END { print c + 0 }' "$dir/yosys.log")"
		[[ $got -eq $n ]] || wrong+=" $typ $got instead of $n"
	done < <(sed -n 's|^// *expected: *\([A-Za-z0-9_]*\) *\([0-9]*\).*|\1 \2|p' "$d")
	if [[ -n $wrong ]]; then
		row "$name" - - "synthesis:$wrong ($dir/yosys.log)"
		runs=$((runs + 1))
		failed=$((failed + 1))
		continue
	fi
	gold="$dir/gold.json"
	rm -f "${gold%.json}".*
	if ! gold_json "$d" "$gold" || ! gold_split "$gold"; then
		row "$name" - - "RTL not readable for the comparison (${gold%.json}.log)"
		runs=$((runs + 1))
		failed=$((failed + 1))
		continue
	fi
	xnf_d+=("$d")
	pcf="${d%.v}.pcf"
	modes=(without)
	[[ -f "$pcf" ]] && modes=(with without)
	for m in "${modes[@]}"; do
		for s in default $SEEDS; do
			opts=()
			[[ $m == with ]] && opts+=(--vopt "pcf=$pcf")
			[[ $s != default ]] && opts+=(--seed "$s")
			queue "$dir/pcf-$m-seed-$s" "$m" "$s" "${opts[@]}"
		done
	done
	# the other packages: without PCF with the default seed (the placer only uses bonded pads)
	for pkg in $PACKAGES; do
		queue "$dir/package-$pkg" "$pkg" default --vopt "package=$pkg"
	done
	# without the clock buffers (--vopt noclkbuf, column Seed: noclkbuf), with and without PCF
	for m in "${modes[@]}"; do
		opts=(--vopt noclkbuf)
		[[ $m == with ]] && opts+=(--vopt "pcf=$pcf")
		queue "$dir/noclkbuf-$m" "$m" noclkbuf "${opts[@]}"
	done
done

# Runs in parallel, at most TEST_JOBS at a time (default JOBS, never more than 10). Every run writes its
# row to a file; rows are printed in queue order as soon as all previous ones are done.
TEST_JOBS="${TEST_JOBS:-$JOBS}"
[[ $TEST_JOBS -le 10 ]] || TEST_JOBS=10
rows="$OUT/.rows"
rm -rf "$rows"
mkdir -p "$rows"
n=${#q_run[@]}
next=0
flush() {
	while [[ $next -lt $n && -e "$rows/$next.done" ]]; do
		if [[ -s "$rows/$next.row" && -f "${q_run[next]}.bad" ]]; then
			cat "$rows/$next.row"
			failed=$((failed + $(cat "${q_run[next]}.bad")))
		else
			row "${q_name[next]}" "${q_m[next]}" "${q_s[next]}" "aborted (${q_run[next]}.*)"
			failed=$((failed + 1))
		fi
		runs=$((runs + 1))
		next=$((next + 1))
	done
}
for ((i = 0; i < n; i++)); do
	while [[ $(jobs -rp | wc -l) -ge $TEST_JOBS ]]; do
		wait -n || true
		flush
	done
	(
		dir="${q_dir[i]}" name="${q_name[i]}" gold="${q_gold[i]}"
		IFS=$'\x1f' read -r -a opts <<<"${q_opts[i]}" || true
		pnr_run "${q_run[i]}" "${q_m[i]}" "${q_s[i]}" "${opts[@]}" >"$rows/$i.row" 2>/dev/null || true
		touch "$rows/$i.done"
	) &
	flush
done
while [[ $(jobs -rp | wc -l) -gt 0 ]]; do
	wait -n || true
	flush
done
flush

# XNF for XACT (xc2064xnf) per design in three variants: from gates, with --lut (logic as EQN) and with
# --iobff (FFs behind inputs in the IOB like xc2064_iobff), each checked with check_xact.py. XNFMAP itself runs
# only in DOSBox, outside the test.
xnf_variants=(gates LUT iobff)
xrow() { printf '%-10s %-7s %-7s %s\n' "$@"; }
xnf_run() {
	local d="$1" dir="$2" name="$3" v f res=() bad=0 pcf=() flags=()
	[[ -f "${d%.v}.pcf" ]] && pcf=(--pcf "${d%.v}.pcf")
	for v in "${xnf_variants[@]}"; do
		flags=()
		[[ $v == LUT ]] && flags=(--lut)
		[[ $v == iobff ]] && flags=(--iobff)
		f="$dir/xnf-$v"
		if YOSYS="$YOSYS" python3 "$ARCH/tools/xc2064xnf" "$d" -o "$f.xnf" "${flags[@]}" >"$f.log" 2>&1 &&
			python3 "$HERE/check_xact.py" xnf "$f.xnf" "$dir/yosys.log" "${flags[@]}" "${pcf[@]}" >>"$f.log" 2>&1; then
			res+=(ok)
		else
			res+=(FAIL)
			bad=$((bad + 1))
		fi
	done
	xrow "$name" "${res[@]}"
	echo "$bad" >"$dir/xnf.bad"
}
xnf_n=0
if [[ ${#xnf_d[@]} -gt 0 ]]; then
	echo
	xrow XNF "${xnf_variants[@]}"
	for ((i = 0; i < ${#xnf_d[@]}; i++)); do
		while [[ $(jobs -rp | wc -l) -ge $TEST_JOBS ]]; do
			wait -n || true
		done
		d="${xnf_d[i]}" name="$(basename "${xnf_d[i]%.v}")"
		rm -f "$OUT/$name"/xnf-* "$OUT/$name/xnf.bad"
		xnf_run "$d" "$OUT/$name" "$name" >"$rows/xnf-$i.row" 2>/dev/null &
	done
	wait
	for ((i = 0; i < ${#xnf_d[@]}; i++)); do
		name="$(basename "${xnf_d[i]%.v}")"
		xnf_n=$((xnf_n + ${#xnf_variants[@]}))
		if [[ -s "$rows/xnf-$i.row" && -f "$OUT/$name/xnf.bad" ]]; then
			cat "$rows/xnf-$i.row"
			failed=$((failed + $(cat "$OUT/$name/xnf.bad")))
		else
			xrow "$name" "aborted ($OUT/$name/xnf-*)"
			failed=$((failed + ${#xnf_variants[@]}))
		fi
	done
fi
rm -rf "$rows"

log "$runs runs and $xnf_n XNF netlists, $failed failed ($TEST_JOBS in parallel). Logs: $OUT"
[[ $failed -eq 0 ]]
