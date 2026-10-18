# Development stages

The model was built in stages; the other documents refer to them as "stage N".

## Open items

- **Latched inputs on `inout` ports** (`XC2000_IOBUF` with FF in the input): XACT can do this; so far the
  model only moves pure inputs into the IOB.
- **Search deeper for FGM**: so far `xc2064_fgm` only merges the D LUT with LUTs directly in front of it.
  Cuts across several levels (or FGM already before `abc`) would find more cases.
- **Real hardware:** open on the way to a loaded chip (all of it needs a real XC2064): the first attempt with the
STM32 loader (D/P pin), and the edge of the IOB FF (rising according to the Data Book) as well as Shirriff's
K mux codes. The clock buffer codes come from XACT's model, not from the chip.

## Towards a real bitstream

[`XC2064-def.txt`](https://github.com/shirriff/xc2064) describes all 11,360
configuration bits (LUT contents, IOB options, PIPs, switch matrices). For loadable bitstreams the PIPs of
the model must correspond exactly to the PIPs of the original. That is why the routing graph is built from
this data, with Shirriff's line names. The bitstream is then generated, as for iCE40, ECP5 and
GateMate, in two steps (implemented in stage 5, see [Bitstream](bitstream.md)):
1. nextpnr writes a readable text file with `--vopt out=<file>`: the used pips and the
   configuration of each Bel (LUT contents, muxes, IOB mode) with Shirriff's or XACT's names.
2. A dedicated tool in `arch/xc2064` (`xc2064pack`, Python) turns it into the RBT or BIT file,
   `xc2064unpack` does the reverse. The table pip or Bel option → bit (pattern) belongs in the pack tool,
   not in nextpnr.

This keeps the file between the steps readable and comparable, and `xc2064unpack` translates real
bitstreams such as Shirriff's `TEST1.RBT` (with `TEST1.LCA`) back into pips and Bel configuration.
`xc2064pack` writes RBT exactly in XACT's format. The goal is that the STM32 loader from
[dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026) can load the files into a real
XC2064-PD48 (success: D/P pin high); that is why the PD48 package exists alongside PC68.

## Stages

1. done: data package `xc2064db`, `xc2064unpack` at bit level, test with the XACT bitstreams (see
   [Data sources](data-sources.md))
2. done: CLB array from the data (`xc2064db.graph`): channels (vertical 5 single-length segments,
   horizontal 4), switch matrices with the real pattern, Long Lines, all PIP crossings, CLB inputs with all
   sources and mux codes, X/Y via their PIP bits; cross-check with `TEST1.LCA`. `xc2064unpack` counts which
   decoded pips the graph knows (`TEST1.RBT`: 124 of 127, the rest at IOBs). This made the router timeouts
   disappear
3. done: IOBs from `iob.js` (`xc2064db.iobmux`): output and T multiplexers with mux codes,
   input via PIP bits, on both channels at the pad, T from 2 local lines and 2 Long Lines,
   on/off/tristate as configuration (`pack()` folds a constant T), both IOBs on the right with X/Y. All
   PIP bits are now in the graph, as are all 127 pips and switch connections of `TEST1.RBT`; the
   GUI draws the IOB pins from the pips. The longest run in the regression test needs 80
   router iterations
4. done: repowering buffers from the Bidi bits (direction confirmed with the XACT bitstreams, derived in
   routing), clock buffers as pips with the bits of their input muxes (codes since stage 11, clock on
   P9/P43 only via the buffer), constants without invented pips (folded into LUT contents or a
   constant LUT), timing of CLB and IOB from the Data Books 1993 (-50) and 1994 (-70/-100/-130),
   interconnect as an RC model. Open: numbers for the interconnect
5. done: configuration of CLB and IOB decoded (`xc2064db.blocks`, checked with `TEST1.LCA`),
   `--vopt out=`, `xc2064pack` in XACT's RBT format (all XACT bitstreams bit-exact in the round trip),
   `xc2064netlist` and the round trip in the regression test (text → RBT → back → netlist → formal
   comparison, 42 of 42), package PD48. nextpnr used the clock buffers only with `--vopt clkbuf` (up to
   stage 11 a design routed this way could not be packed; since stage 12 they are the default)
6. done: mux mode FGM: primitive `XC2000_FGM`, Bel `FGM` on the lines of F, G and FG,
   `pack()` and legality (both tables with separate inputs, Q on input 3, a fixed S becomes a LUT3),
   `--vopt out=` with `BASE:FGM`, `xc2064netlist`, the yosys pass `xc2064_fgm` and the example
   `shiftreg.v` (8 FGM instead of 9 LUT3 and 7 LUT4, 8 instead of 16 CLBs)
7. done: latched inputs: the four K muxes from `iob.js` in the data package and in the graph (clock line
   per side, `mux P9.K …` in the text format instead of a field K), primitive `XC2000_INFF` with Bel pin K,
   same clock per side as a legality rule, timing T_LI/T_PL/T_LP, the yosys pass `xc2064_iobff`,
   `xc2064netlist` and the example `inreg.v`; the GUI draws FF, input multiplexer, clock lines
   and K muxes
8. done: timing of the storage element as a variant per cell (FF rising/falling, latch with
   transparency D → Q from T_ITO, set/reset → Q from T_RIO/T_RLO, arcs only without a combinational loop)
   and the packages PC44 and PG68 (pin tables of both Data Books compared, in the regression test one run
   per design in PD48, PC44 and PG68)
9. done: regression test in parallel (at most 10 runs at a time, 85 runs in just under 1 min) and the
   independent cross-check with Shirriff's decoder (QuickJS, `xc2064shirriff`) in `run.sh` and
   `bitstreams.sh`: it decodes all XACT bitstreams and all generated bitstreams the same way as the package
10. done: larger test designs (`uart_tx.v` 46 CLBs, `ampel.v` 19, `bcd7seg.v` 54) with PCF. Found
   and fixed under load: the placer found no legal placement for dense designs (LUT3 pairs in
   `pack()`), CLBs with three outgoing signals were allowed (new rule: at most X and Y),
   the Q feedback of a G LUT went through the routing (now input 3), yosys re-encoded state machines
   (now `-nofsm`) and the comparison failed on a ROM in the RTL (`proc -norom`). Limit: from about
   90% occupied CLBs, router2 in the debug build needs minutes or does not finish within 300 s
11. done: codes of the clock buffer inputs with MAKEBITS as an oracle (see
   [Clock buffer inputs](xact.md#clock-buffer-inputs-makebits)): `iobmux.clkmuxes` with 6 or 7 sources, all of them
   except the oscillator in the graph, `mux CLK.AA.I …` in the text format; with this the package decodes all
   used bits. Designs routed with `--vopt clkbuf` can be packed (in the regression test per design with and
   without PCF). The PIPs from ACLK onto the long.2 are directional. `xc2064lca` writes a configuration as
   LCA for MAKEBITS; for this, iob.js entries without a line (X/Y directly to the pad, GCLK at P9.O and the
   K muxes) now have their crossing. `xc2064db.bitstream` also reads RBT files from MAKEBITS 5.2.0
12. done: clock buffers as the default. `--vopt noclkbuf` turns them off, `--vopt clkbuf` remains allowed
   and no longer changes anything. P11 and P46 are further pads of GCLK and ACLK respectively: `pack()` places
   clocks without a pin there if P9 or P43 is taken or not bonded (PG68: ACLK via P46), and there, too,
   `preRoute()` routes a clock that clocks only storage elements entirely via the buffer (two such clocks on
   one buffer: the one with the most storage elements gets it). In the regression test the two extra runs
   per design run without buffers (`noclkbuf`), all others must use one; MAKEBITS sets clocks on P11 and
   P46 the same way as `xc2064pack`. This makes every bitstream with a clock from a pad depend on the
   buffer codes from MAKEBITS; anyone who, for a first attempt on the chip, wants to program only bits
   that XACT bitstreams also use should take `--vopt noclkbuf`
13. done: direction of the repowering buffers as with XACT, also where there is no sink behind the
   buffer: away from the driver (previously the default setting, which could point into the net as a
   second driver). The XACT bitstreams confirm this on 30 buffers, and 44 runs are bit-identical with
   MAKEBITS (see [Clock buffer inputs](xact.md#clock-buffer-inputs-makebits)); `xc2064pack --compare` compares
   bit-exactly for this purpose

After every stage, `test/run.sh` must pass for all examples (Net, Pips and, since stage 5, Bitstream). The
GUI keeps CLB and IOBs in datasheet style; only the channels follow the line layout from Shirriff.
