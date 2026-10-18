# nextpnr uarch

The nextpnr part is a Himbächel uarch in `nextpnr/`: `xc2064_arch_gen.py` generates the chip database from
the data package `xc2064db` (see [Data sources](data-sources.md)), and `xc2064.cc` implements the legality
checks, packing, pin constraints, routing setup, timing and the [GUI](gui.md) drawing. The modelled
elements and their timing are listed in [Architecture model](architecture.md).

## Legality checks

`isBelLocationValid` checks per CLB:

1. FG (4 variables) or FGM (mux mode) and F/G (3 variables) are mutually exclusive.
2. The storage element gets its data only from F or FG of the same CLB.
3. All inputs (LUT pins, clock, set, reset) can be supplied via the multiplexers of the original, with A–D
   each carrying at most one signal. This is an exact assignment check (backtracking). Internal sources
   (Q, F, G) and K (from long.2 or GCLK) occupy none of the inputs.
4. At most two signals leave the CLB, because there are only X and Y. Only the fixed paths F → D and set,
   G → reset and clock, and Q → input 3 stay inside the CLB. Without this rule a CLB with F, G and FF
   could be formed whose three outputs the router can never accommodate (found with `bcd7seg.v`).

Per IOB, `isBelLocationValid` checks that all latched inputs (`XC2000_INFF`) on one chip side are on the
same clock, because they share a clock line. If PCF already fixes them differently, `pack()` aborts with
a message.

## Packing

`pack()` keeps LUT and FF together as a cluster. If the FF's own output Q is not on input 3 of the LUT,
`pack()` swaps the inputs and permutes INIT so that the Q feedback is used. An unused LUT input still
reads a line in the chip (the default setting of its mux); `pack()` therefore makes the LUT contents
independent of it.

If a design has more LUT cells than the chip has CLBs (64), `pack()` places LUT3s in pairs as F and G in one
CLB (`pair_lut3`). Otherwise the placer (HeAP) spreads the LUT3s individually over the chip, and no room is
left for LUT4 and FGM, which need a whole CLB ("Unable to find legal placement", found with `bcd7seg.v`:
52 LUT3 and 28 LUT4). A LUT3/FF cluster takes a free LUT3 as G, otherwise two free LUT3s form a new
cluster. Priority goes to LUTs that supply reset or clock of the FF or read its Q (both stay inside the
CLB, Q then on input 3), then to the number of shared inputs; pairs with nothing in common only as long as
more than 85% of the CLBs would be needed. Each pair is checked with the same rule as
`isBelLocationValid`.

A constant T is not a signal in the original but the mode of the IOB (code of the T multiplexer), and the
routing graph has no pips for it. `pack()` therefore turns `XC2000_TOBUF`/`XC2000_IOBUF` with T = 0 into an
`XC2000_OUTBUF` (for `IOBUF` the users of O then read I directly) and with T = 1 into an `XC2000_INBUF`
(note in the log).

## Primitives

The primitives carry the family prefix `XC2000_` (like `CC_` for GateMate) so that they cannot be confused
with cells of other libraries: `XC2000_LUT3`, `XC2000_LUT4`, `XC2000_DFF` and the IO buffers `XC2000_INBUF`,
`XC2000_INFF` (latched input), `XC2000_OUTBUF`, `XC2000_TOBUF` (tristate output) and `XC2000_IOBUF`
(bidirectional, like `CC_TOBUF`/`CC_IOBUF` for GateMate). The Bel types in the chip database stay short
(`LUT3`, `LUT4`, `DFF`, `IOB`); `getBelBucketForCellType()` maps them. For the counterpart in yosys see
[Synthesis](yosys.md).

## Pin constraints (PCF) and clock placement

Pins are given in a **PCF file** as for iCE40 (`set_io [-nowarn] <Port> <Pin>`, buses as `leds[0]`, pins as
package pins: P2…P68 in the PC68, P1…P48 in the PD48, P2…P44 in the PC44, A2…L10 in the PG68), which nextpnr
reads with `--vopt pcf=<file>`. `flow.sh` automatically picks up `design.pcf` next to `design.v`; `PCF=…`
selects a different one. Without an entry the placer decides. `pack()` itself places clocks on the pads of
the clock buffers (except with `--vopt noclkbuf`): the net with the most storage elements on GCLK (P9, or P11
if P9 is taken), the next one on ACLK (P43, otherwise P46, e.g. in the PG68, which lacks P43). If a clock is
already constrained to a pad of a buffer, that buffer stays with it; a clock constrained to a pad without a
buffer stays there (note in the log). If two nets on P9 and P11 (or P43 and P46) clock only storage
elements, the one with the most gets the buffer and the other runs over general routing (note in the
log). Alternatively, `(* LOC="P9" *)` on an IO buffer in the Verilog still works; the PCF file takes
precedence. `pack()` fixes these pads already during packing (like GateMate), so the GUI shows them as
occupied right after "Pack". It does not set a BEL attribute in doing so, otherwise the placer would try to
bind the cells a second time.

## Routing

The default router is `router2`. It searches each net only within its bounding box plus a margin of
normally 3 tiles. With tight channels this is not always enough: two nets then keep alternating on a
wire, and router2 never finishes (it has no abort limit). `preRoute()` therefore sets the margin to the
chip size unless the settings `router2/bbMargin/x` and `/y` are already set. `--router router1` remains
possible.

With the guessed routing graph before [stage 2](development-stages.md#stages) (4 tracks per channel, assumed matrix patterns, 6–7 sources
per CLB input), two placements in the regression test ran into the timeout, and one needed 26,500
iterations. With the graph from the data (5 vertical single-length segments, the real matrix pattern, up to
10 sources per input) all 42 runs route, the longest needs 593 iterations, the whole test 54 s instead of
11.5 min. With the IOBs from `iob.js` (stage 3, pads on both channels) the longest run needs 80 iterations,
with the timing from stage 4 117. The test's *Routing* column shows this. With the round trip through the
bitstream (stage 5) the whole test takes about 4 min, with `shiftreg.v` and `inreg.v` (stages 6 and 7) and
the runs in PD48, PC44 and PG68 (stage 8, 85 runs in total, the longest with 97 iterations) just under
4 min when nothing else is running. Since the runs execute in parallel (stage 9, 10 jobs), the whole test
including the cross-check via Shirriff's decoder takes just under 1 min, with the larger designs from
stage 10 (136 runs, the longest with 1238 iterations) just under 3 min, with the runs through the clock
buffers from stage 11 (152 runs) 2.5–3 min. With the clock buffers as the default (stage 12, the clock of
the examples runs over GCLK instead of over the long.2 of each column) the longest run needs 276
iterations, the whole test a good 2 min, with the LCA and XNF checks (152 runs, 24 XNF netlists) just
under 3 min.
