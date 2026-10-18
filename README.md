# Architecture `xc2064`: model of the Xilinx XC2064

The XC2064 (1985) was the first FPGA: 64 Configurable Logic Blocks (CLBs) in an 8×8 grid and
58 I/O pins (PLCC68). This architecture models it as a nextpnr Himbächel uarch, with a yosys plugin,
place & route, timing and a complete schematic view in the GUI. From the result, `tools/xc2064pack`
produces a bitstream (RBT in XACT's format, see [Bitstream](#bitstream)); none has been loaded onto a
real chip yet.

References:
- XC2000 datasheet
- Ken Shirriff, [Reverse-engineering the first FPGA chip, the XC2064](https://www.righto.com/2020/09/reverse-engineering-first-fpga-chip.html)
- his bitstream decoder [shirriff/xc2064](https://github.com/shirriff/xc2064), whose `clb.js` and `iob.js`
  supplied the input multiplexers of the CLBs, the options of the storage element, the pad table and the
  multiplexers and PIPs of the IOBs; the decoder itself runs without a browser as a cross-check
  (`tools/xc2064shirriff`, see [Regression test](#regression-test))
- [rates37/openxc2064](https://github.com/rates37/openxc2064) with bitstreams from Xilinx's XACT
- Xilinx *The Programmable Logic Data Book* 1994 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1994_Xilinx_Programmable_Logic_Data_Book.pdf)),
  XC2000 section pp. 2-216 to 2-222: component availability and the timing tables of CLB and IOB (-70, -100, -130)
- the same from 1993 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1993_Xilinx_Programmable_Logic_Data_Book.pdf)),
  pp. 2-208 to 2-214: the same tables with -50, -70 and -100
- `MAKEBITS` from Xilinx XACT 5.2.0 as a black box (in DOSBox, outside the repo): codes of the
  clock buffer inputs and cross-check for `xc2064pack` (see [Clock buffer inputs](#clock-buffer-inputs-makebits));
  `XNFMAP` and `MAP2LCA` for comparing the mapping onto CLBs (see [XNF for XACT](#xnf-for-xact-toolsxc2064xnf))

Both repos are submodules of this repo ([swittlich/prjfreeman](https://github.com/swittlich/prjfreeman)) under
`external/`, at the commits listed in [Data sources](#data-sources-and-bitstream-tools). The repo sits as
`arch/xc2064` in the repo that builds nextpnr and yosys (`scripts/build-nextpnr.sh`); all paths in this README
are relative to that repo's root:

```bash
git clone --recurse-submodules https://github.com/swittlich/prjfreeman arch/xc2064   # fresh clone, with submodules
git -C arch/xc2064 submodule update --init                                            # already cloned: fetch the submodules
```

## What is modelled

| Element | Model | Source / deviation |
|---|---|---|
| Grid | 8×8 CLBs (X1Y1…X8Y8) plus IO ring. Shirriff's 9×9 tiles AA…II correspond to X1Y1…X9Y9. Each tile contains the channels above and to the left of its CLB; the 9th column/row only routing and pads | Shirriff |
| Routing graph | Built from the data (`xc2064db.graph`): every pip is a PIP bit, a Magic bit of a switch matrix or a mux code of a CLB input or of an IOB multiplexer; the lines carry Shirriff's or XACT's names. The inputs of the two clock buffers are mux codes as well | `XC2064-def.txt`, `draw.js`, `clb.js`, `iob.js`, clock buffer codes from `MAKEBITS`; checked with `TEST1.LCA` (see [Data sources](#data-sources-and-bitstream-tools)) |
| Switch matrices | 2 per crossing (8.1, 8.2), none at the four corners, 8 pins. Inside, 20 connections following the pattern of the Magic bits (each pin to 5 of the other 7); at the edge the same without the pins of the missing side. 8.1 connects vertical local.1/2, 8.2 local.3/4, each with two horizontal lines (mirrored in row I) | Magic bits; datasheet Figure 7b; cross-check `possible_connections` (openxc2064) |
| Single-length segments | Vertical: local.1-4 from matrix to matrix and the fifth line local.5; horizontal: 4 (inside local.1/3/4/5, at the edge local.1-4) | Datasheet *General-Purpose Interconnect*: 5 vertical, 4 horizontal segments, each one block long |
| Repowering buffers | 158, one on each single-length segment that crosses a boundary of the 9 sections: vertically just before the channel of rows D and G, horizontally before that of columns D and G. One bit selects the direction (0: down or right, 1: up or left); it is never off. Therefore it does not split the segment in the routing graph; the direction follows from the routing (`xc2064db.graph.bidi_bit`), as with XACT: away from the net's driver, even if only an unused piece lies beyond it | Bidi bits of the bit map (G position = line); direction confirmed with `TEST1.RBT` and `AND_OR.BIT` (30 buffers, no contradiction) and with MAKEBITS; datasheet *Interconnect* |
| Fifth vertical line | Does not pass any matrix. Its piece in row R starts at a connection point at the top of the channel (`row.R.local.0`), crosses local.3/4 there on the track of local.6, bends onto the track of local.5, runs past the CLB (B, C, Y) and in the channel below also crosses local.0, local.3 and local.4 | Datasheet Figure 7b (dashed); confirmed by net `p1` in `TEST1.LCA` |
| Function generators | `F`, `G` (primitive `XC2000_LUT3`): input 1 from {A, B}, input 2 from {B, C}, input 3 from {C, D, **Q**} | `clb.js` |
| 4-variable mode | `FG` (`XC2000_LUT4`): inputs as for F/G, **B** selects between F and G (I[3]), occupies both | `clb.js` |
| Mux mode | `FGM` (`XC2000_FGM`): F and G with **separate** inputs (`F[2:0]`, `G[2:0]`), **B** (`S`) selects (1: F), the output M is on F and G. In the bits the same mode as FG, only the input muxes of F and G are set differently. It is only worthwhile with the Q feedback: F reads D, G its own Q (or vice versa), i.e. a function of 5 signals `S ? f(a, c, x) : g(a, c, Q)`. The pass `xc2064_fgm` forms it from LUTs in front of an FF | Data Book 1993, *CLB Combinatorial Logic Options* (pp. 2-182/2-183, "Option 3", "D and Q never in the same function"); `clb.js`; `TEST1.LCA` (CLB AA, there without used outputs) |
| Storage element | `XC2000_DFF`: flip-flop or **latch** (`LATCH`), clock from **K, C or G**, **invertible** (`CLKINV`), asynchronous **set from A or F**, **reset from D or G**, data from F or FG | `clb.js`; reset assumed to take priority over set |
| Outputs | X, Y each from Q, F or G, both into the vertical channel to the **right** of the CLB: X (line io6) onto local.2, local.4 and long.1, Y (line y) onto local.1, local.3, local.5 and long.2. In column H the crossings are in the edge channel: X (at the height of line b) onto local.2, local.4 and long.2, Y onto local.1, local.3, long.1 and long.3 | PIP bits of the bit map |
| CLB inputs | All sources from `clb.js` with their mux codes: A 6–7 (channel above, long.1, X from above), B 10 (local.1-5, Y from the left, long.1/2, GCLK, X from above), C 8 (local.1-5, long.1/2, X from below), D 6–7 (channel below, long.1, X from below), K 2 (long.2, GCLK); at the edge other lines and pads | `clb.js`; checked with all XACT bitstreams and `TEST1.RBT` |
| Direct connections | X hard-wired to A/B of the CLB below and C/D of the CLB above, Y hard-wired to B of the CLB to the right (track local.6). At the edge, pads take over these sources | Datasheet *Direct Interconnect* and Figure 9; sources in `clb.js` |
| Long Lines | Vertical: 2 per column (column A: long.2–4, column I: long.1–3), horizontal: 1 per row (row A: long.2/3, row I: long.1/2) | Datasheet *Longlines*: additional Long Line next to each IOB row |
| Clock nets | GCLK (`CLK.AA.O` at the top and `col.*.clk` per column) onto B and K of every CLB, ACLK (`row.I.clk` at the bottom) via PIPs onto the vertical long.2 (column A: long.4) and from there onto K, B or C. The input muxes of the buffers: `CLK.AA.I` (GCLK, 6 bits) selects P9, P11, `col.A.local.3`, `col.A.long.3`, `row.A.long.3` or, in the default setting, `row.A.local.3`; `CLK.II.I` (ACLK, 8 bits) P43, P46, `col.I.local.2`, `col.I.long.2`, `row.I.long.1`, in the default setting `row.I.local.2`, or the crystal oscillator (no Bel, not in the graph). Because a buffer always drives, the PIPs from ACLK onto the long.2 are directional: ACLK is not a free routing path. nextpnr uses the buffers by default: a clock on P9 or P11 (GCLK) or on P43 or P46 (ACLK) that clocks only storage elements runs entirely through its buffer, and `pack()` places clocks without a pin on these pads. `--vopt noclkbuf` disables the buffer inputs; a clock then runs like any other signal, to K via the vertical long.2 of the column (this is how XACT clocks in `COUNTER.BIT`) | Datasheet *Longlines*, Figure 8b; codes from `MAKEBITS` (see [Clock buffer inputs](#clock-buffer-inputs-makebits)) |
| Constants | No constant line, as in the original: `pack()` folds a constant LUT input into the LUT contents, drops set/reset = 0 and inserts a LUT with fixed contents for everything else (constant pad output, set = 1, …) | – |
| Package | `--vopt package=PC68` (default, 68-pin PLCC, all 58 pads, pin = pad), `PD48` (48-pin DIL, 40 pads; -50 only), `PC44` (44-pin PLCC, 34 pads; -70, -100) or `PG68` (68-pin PGA, pins A2…L10, 57 pads; -50, -70, -100). PCF and LOC name the package pin; the placer only uses bonded pads. The two Data Books differ in two places: PC44 pin 20 is on P30 in 1994, on P31 in 1993. The 1994 version applies here, because on the XC2018 PC44 pin 20, like P30 of the XC2064, is the configuration pin LDC (the family is pin-compatible in the PC44). 1993 gives the PGA pin of P65 as B8, 1994 as D8 (not an edge pin); B8 here. For P43 (XTL2 or I/O) and RESET neither gives a PGA pin (K10 and L10 are left over), so P43 is missing in the PG68 | *Configuration Pin Assignments* (Data Book 1994 p. 2-214, 1993 p. 2-206, XC2018 p. 2-207) and *Component Availability* (1993 p. 2-208, 1994 p. 2-216); `xc2064db/packages.py` |
| IOBs | **58 pads with PLCC68 names** (Bel `P9` etc.), up to two per pad tile. All connections from `iob.js`, on the lines of **both channels** at the pad (parallel and perpendicular to the edge): output to the pad (Bel pin I, "O" in the datasheet) via a multiplexer with a mux code from 6–9 sources (single-length segments, Long Lines, X/Y of the edge CLB, GCLK at P9, ACLK at P43). Tristate T (1 turns the driver off) via a multiplexer from 2 single-length segments and 2 Long Lines of the channel parallel to the edge. Input from the pad (Bel pin O) via PIP bits onto 5–7 lines and hard-wired to inputs of the edge CLB. The mode of the output driver is configuration (code of the T multiplexer), not a pip: on (`XC2000_OUTBUF`), off (`XC2000_INBUF`) or tristate (`XC2000_TOBUF`, `XC2000_IOBUF`, T routed). Direct connections: on the right, both pads take X and Y of a CLB in column H (the first one of the CLB next to it, the second one of the CLB above); at the top the first pad drives A and B, the second takes X of the CLB to the left; at the bottom the first pad drives C and D, the second takes X; on the left the second pad drives B of the CLB above, P24 B of CLB HA. The IOB at the top thus behaves like a CLB above, the one at the bottom like one below | `iob.js`; datasheet, sections *I/O Block* and *Direct Interconnect*. The crossings without a PIP bit at P9 and P11 (`col.A.io2`) and the input of P43 (`@aclk_in`) are sources of the clock buffer muxes; 6 further crossings with `col.A.io2` (P13–P23) are missing, for `MAKEBITS` they are not programmable |
| Latched inputs | `XC2000_INFF` (PAD, K → O): the FF between pad and input that the input multiplexer selects instead of the direct path (XACT `I:Q`). Rising edge, 0 after loading, no set/reset, no clock inversion. Clock: **one clock line per chip side** along the outside of the edge (top `row.A.local.0`, right `col.I.local.5`, bottom `row.I.local.5`, left `col.A.local.0`), to which the clock input of every IOB on that side is hard-wired (nodes `IOCLK.T/R/B/L`). It is fed by a **K mux** at a corner with a code (4 bits that the bit map assigns to P9, P59, P27 or P24 respectively) from the edge channel of the same side: top GCLK, `row.A.local.1-4`, `row.A.long.3`; right `col.I.long.2`, `col.I.local.1-4`; bottom `row.I.long.1`, `row.I.local.1-4`; left `col.A.local.1-4`, `col.A.long.3`, GCLK. All latched inputs on one side therefore have the same clock (`isBelLocationValid`; with PCF an error in `pack()`). One source each on the right and at the bottom (`col.I.io3`, `row.I.io4`) is a stub whose signal is unknown, and is missing | Data Book 1993, *I/O Block* (pp. 2-180/2-181, Figure 3: "edge-triggered D flip-flop", "I/O Blocks along each edge of the die share common clocks") and *IOB Switching Guidelines* (p. 2-214: setup/hold at the rising edge); `iob.js` (kin, the four K muxes with codes); `TEST1.LCA` (P8 `I:Q`, K mux at the top on code 8 = `row.A.local.1`, one of the two crossings that XACT names there). Not checked on the chip: edge and codes |
| Timing | Speed grades via the device name: `XC2064-50`, `-70`, `-100`, `-130` (no suffix: -70; the number is the toggle rate of an FF in MHz). CLB and IOB according to the Data Book tables, at -70: T_ILO 10 ns (input to output, in the model 6 ns function = T_QLO plus 4 ns output driver), T_CKO 10 ns (6 ns clock-to-Q plus driver), T_ICK 7 ns (so setup at D is 1 ns), clock via C 3 ns and via G 4 ns later than via K (from T_CCO, T_CIO), pad to input T_PID 6 ns, output to pad T_OP 9 ns, T to pad 15 ns. Interconnect as an RC chain: each switch (switch matrix, PIP, input mux) is a resistance in front of the capacitance of the line behind it; the chain restarts at every driver (CLB output, clock buffer); at -70 a single-length segment behind a switch costs about 0.5 ns, a Long Line 4 ns, the clock buffer 4 ns, the other speed grades in proportion to T_ILO | Xilinx *Programmable Logic Data Book*, XC2000 *CLB Switching Characteristic Guidelines* and *IOB Switching Guidelines*: -50 (the only grade in the PD48) from the 1993 edition (pp. 2-213, 2-214), -130 from the 1994 edition (pp. 2-221, 2-222), -70 and -100 are the same in both. At -50: T_ILO 15, T_QLO 8, T_CKO 15, T_ICK 9, T_CCO 19, T_CIO 27, T_PID 8, T_OP 12, T_THZ/T_TON 20 ns. For the interconnect the book gives no numbers, only the RC model (*Interconnect Performance*): R, C and the clock buffer are estimates. The repowering buffers end the RC chain in the original, but not in the model (which errs on the slow side). Storage element: `pack()` selects a timing variant per cell (FF with rising or falling edge, latch transparent at clock 1 or 0 with setup and hold at the closing edge). Set/reset are combinational arcs S/R → Q = T_RLO − T_ILO (-70: 11 ns), so the path via F or G gives exactly T_RLO; directly from A or D the pip class SRDIR = T_RIO − T_RLO + T_QLO is added (-70: 1 ns, T_RIO in total). For the latch, D → Q = T_ITO − T_ILO (-70: 4 ns), so via F it is T_ITO. If such an arc would close a combinational loop (Q via logic back to D, S or R), `pack()` omits it, otherwise nextpnr's timing analysis would abort. Not modelled: T_RS, T_RPW and T_MRQ (RESET pin). Latched input: clock to input T_LI (-50/-70/-100/-130: 15/11/8/7.5 ns), setup at the pad T_PL (8/6/4/2 ns), hold T_LP (0, at -130 4 ns); the clock line of a side counts like a Long Line |

### Rules in `nextpnr/xc2064.cc`

`isBelLocationValid` checks per CLB:

1. FG (4 variables) or FGM (mux mode) and F/G (3 variables) are mutually exclusive.
2. The storage element gets its data only from F or FG of the same CLB.
3. All inputs (LUT pins, clock, set, reset) can be supplied via the multiplexers of the original, with A–D
   each carrying at most one signal. This is an exact assignment check (backtracking). Internal sources
   (Q, F, G) and K (from long.2 or GCLK) occupy none of the inputs.
4. At most two signals leave the CLB, because there are only X and Y. Only the fixed paths F → D and set,
   G → reset and clock, and Q → input 3 stay inside the CLB. Without this rule a CLB with F, G and FF
   could be formed whose three outputs the router can never accommodate (found with `bcd7seg.v`).

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

Per IOB, `isBelLocationValid` checks that all latched inputs (`XC2000_INFF`) on one chip side are on the
same clock, because they share a clock line. If PCF already fixes them differently, `pack()` aborts with
a message.

A constant T is not a signal in the original but the mode of the IOB (code of the T multiplexer), and the
routing graph has no pips for it. `pack()` therefore turns `XC2000_TOBUF`/`XC2000_IOBUF` with T = 0 into an
`XC2000_OUTBUF` (for `IOBUF` the users of O then read I directly) and with T = 1 into an `XC2000_INBUF`
(note in the log).

The primitives carry the family prefix `XC2000_` (like `CC_` for GateMate) so that they cannot be confused
with cells of other libraries: `XC2000_LUT3`, `XC2000_LUT4`, `XC2000_DFF` and the IO buffers `XC2000_INBUF`,
`XC2000_INFF` (latched input), `XC2000_OUTBUF`, `XC2000_TOBUF` (tristate output) and `XC2000_IOBUF`
(bidirectional, like `CC_TOBUF`/`CC_IOBUF` for GateMate). The Bel types in the chip database stay short
(`LUT3`, `LUT4`, `DFF`, `IOB`); `getBelBucketForCellType()` maps them. For the counterpart in yosys see
below.

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

yosys (`yosys/synth_xc2064.cc`):
- Tristate as with GateMate: after flattening, `tribuf -logic` turns internal tristate nets into logic,
  and `deminout` turns `inout` ports that are only read into inputs. `iopadmap` inserts `XC2000_TOBUF` or
  `XC2000_IOBUF` at ports with a tristate driver, and does so before LUT mapping. The inverter (enable in
  yosys, T = 1 turns the driver off) is then still absorbed into a LUT, and with an active-low enable it
  disappears entirely.
- State machines keep the encoding from the RTL (`synth -nofsm`): yosys would often re-encode them as
  one-hot, which is expensive on the XC2064 with one FF per CLB (`ampel.v`: 11 instead of 9 FFs), and the
  state register would no longer be named as in the RTL, which breaks the formal comparison in the
  regression test. `synth_xc2064 -fsm` enables re-encoding.
- `abc -lut 3:4` rates a LUT4 at the cost of two LUT3s.
- `dfflegalize` allows FF and latch with both clock polarities and asynchronous set/reset.
- The pass `xc2064_fgm` (after LUT mapping, can be disabled with `synth_xc2064 -nofgm`) merges the LUT in
  front of a storage element with the LUTs before it that feed only it, if the whole is a function of
  exactly 5 signals, including its own Q, and has the form `S ? f(a, c, x) : g(a, c, Q)` (or with F and G
  swapped). It then becomes an `XC2000_FGM`: S on B, a and c on inputs 1 and 2 of both tables, x or Q on
  input 3. With fewer signals a LUT4 suffices; without Q, FGM gains nothing. So far the pass only checks
  LUTs directly in front of the D LUT (one level)
- The pass `xc2064_iobff` (can be disabled with `-noiobff`) moves an FF into the IOB if its D is connected
  directly to an input, nothing else reads that input, and the FF switches on the rising edge without
  set/reset: `XC2000_INBUF` and `XC2000_DFF` become an `XC2000_INFF`. This saves one CLB per input.
  Inputs of `inout` ports (`XC2000_IOBUF`) stay direct
- The pass `xc2064_ffbuf` gives each FF its own driving LUT (or FGM).
- The custom cell types are not in yosys' `kernel/constids.inc`. `ID(...)` does not work for them with
  current yosys (Twine IdStrings); the pass creates them with `design->twines().add(...)`.

The default router is `router2`. It searches each net only within its bounding box plus a margin of
normally 3 tiles. With tight channels this is not always enough: two nets then keep alternating on a
wire, and router2 never finishes (it has no abort limit). `preRoute()` therefore sets the margin to the
chip size unless the settings `router2/bbMargin/x` and `/y` are already set. `--router router1` remains
possible.

With the guessed routing graph before stage 2 (4 tracks per channel, assumed matrix patterns, 6–7 sources
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

## Flow

```bash
scripts/build-nextpnr.sh debug              # after changes to nextpnr/* (incl. the generator)
arch/xc2064/flow.sh                         # synthesis + place & route with examples/blinky.pcf (5 MHz, FREQ=… changes it)
SEED=1 arch/xc2064/flow.sh                  # with a fixed nextpnr seed (without SEED: nextpnr default)
arch/xc2064/flow.sh arch/xc2064/examples/latch_sr.v   # a different design
arch/xc2064/flow.sh --gui                   # with the nextpnr GUI: Pack, Place, Route via the toolbar
arch/xc2064/test/run.sh                     # regression test (see below)
arch/xc2064/test/bitstreams.sh              # check data sources, xc2064unpack, xc2064pack and Shirriff's decoder with XACT bitstreams
nextpnr-himbaechel --device XC2064 --json build/flows/xc2064/blinky.pnr.json --gui   # view the routed result
```

### Bitstream

```bash
arch/xc2064/flow.sh arch/xc2064/examples/blinky.v --vopt out=build/flows/xc2064/blinky.cfg.txt
python3 arch/xc2064/tools/xc2064pack build/flows/xc2064/blinky.cfg.txt -o build/flows/xc2064/blinky.rbt
python3 arch/xc2064/tools/xc2064unpack build/flows/xc2064/blinky.rbt -o blinky.txt     # reverse direction, as text
python3 arch/xc2064/tools/xc2064netlist build/flows/xc2064/blinky.rbt --meta build/flows/xc2064/blinky.cfg.txt -o blinky.bit.v
```

For the XC2064-50PD48, add `--device XC2064-50 --vopt package=PD48` and a PCF with the DIL pins;
likewise `--vopt package=PC44` (pins P2…P44) or `PG68` (pins like B5);
`xc2064pack` carries the package from the text file into the RBT header (`2064PD48`, `2064PC44`, …). The RBT
file has exactly XACT's layout (7 text lines, header, 160 frames, `11111111`, CRLF), for the STM32 loader from
[dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026); `-o file.bit` writes the binary
form instead.

nextpnr loads an already routed `*.pnr.json` directly in the GUI. On the command line it needs
`--no-pack`, since the result is already packed. A different speed grade is selected by the device name,
e.g. `--device XC2064-50` for the XC2064-PD48 (no suffix: -70).

| Example | Contents | Result |
|---|---|---|
| `examples/blinky.v` | 16-bit counter, pins in `blinky.pcf` (clock on P9, everything on the top edge) | 20 LUT3, 7 LUT4, 16 FF, at -70 13.9–14.3 MHz depending on the seed (default seed 14.0 MHz, seed 1 with `flow.sh --seed 1` or `SEED=1 arch/xc2064/flow.sh` 14.1 MHz), at -50 9.5 MHz (9.4 MHz in the PD48). Without PCF (`PCF=/dev/null`) 13.7–14.4 MHz depending on the seed. The clock runs over GCLK; without the clock buffers (`--vopt noclkbuf`, over the long.2 of each column) 14.4 MHz with PCF. The values shift with every change to the routing graph and timing. The critical path is the LUT levels of the counter logic; a carry chain only came with the XC4000 |
| `examples/latch_sr.v` | FF with falling edge, FF with asynchronous set/reset, latch, pins in `latch_sr.pcf` | 3 storage elements with `CLKINV`, `S`/`R` and `LATCH` respectively. Without PCF, `clk` goes to P9 (GCLK) and the latch enable `en` to P43 (ACLK), in the PG68 to P46 |
| `examples/tristate.v` | 4-bit bus (`inout`) with active-low `oe_n`, tristate output `tout` with `en_n`, pins in `tristate.pcf` (everything on the top edge) | 4 `XC2000_IOBUF`, 1 `XC2000_TOBUF`, 7 LUT3, 1 LUT4, 8 FF, at -70 54–56.5 MHz depending on the seed (-50: 38.8 MHz). T of all bus bits is connected to the pad of `oe_n` without logic and runs over a Long Line of the top edge channel (the T sources there: 2 single-length segments and 2 Long Lines). With an active-high enable (inverter in a CLB whose outputs do not reach the horizontal Long Lines, so only via the tracks to the T inputs) the bus was not routable there |
| `examples/shiftreg.v` | 8-bit shift register with parallel load (`load`, `din`) and enable (`en`, `sin`), pins in `shiftreg.pcf` (control and `din` at the top, `q` on the right) | 8 `XC2000_FGM`, 8 FF in 8 CLBs: each bit is `load ? din[i] : (en ? q[i-1] : q[i])`, F reads `din[i]` on D, G reads `en`, `q[i-1]` and its own Q, B = `load` selects. At -70 54–57 MHz depending on the seed (-50: 39 MHz). With `synth_xc2064 -nofgm` 9 LUT3 and 7 LUT4 in 16 CLBs, 34.8 MHz (default seed with PCF) |
| `examples/inreg.v` | Inputs via the FF in the IOB: `d` into the IOBs, a second register stage in the CLBs and an edge detector (`rise`); pins in `inreg.pcf` (`d[1:0]` at the top, `d[3:2]` on the left, i.e. two K muxes on the same clock) | 4 `XC2000_INFF`, 4 FF, 8 LUT3 in 8 CLBs. The clock reaches the K muxes at the top and on the left via GCLK, without the clock buffers (`--vopt noclkbuf`) at the top via `row.A.long.3`, on the left via `col.A.long.3`. At -70 53–55 MHz depending on the seed. With `synth_xc2064 -noiobff` 8 FF and 12 LUT3 in 10 CLBs, 58.8 MHz (default seed with PCF): T_LI (11 ns) is longer than the clock-to-out of a CLB, and the clock of the IOBs runs over the K mux and the side's clock line |
| `examples/uart_tx.v` | UART transmitter 8N1 (`start`, `data`, `tx`, `busy`; 434 clocks per bit), pins in `uart_tx.pcf` (inputs at the top, `tx` and `busy` on the right) | 23 FF, 7 `XC2000_FGM`, 23 LUT3, 22 LUT4 in 46 CLBs. At -70 15.5–16.2 MHz depending on the seed, router2 needs up to 142 iterations. The shift register with load uses the mux mode FGM |
| `examples/ampel.v` | State machine: pedestrian traffic light with push button, shared phase counter and stored request, pins in `ampel.pcf` | 9 FF (state binary as in the RTL, see yosys above), 17 LUT3, 6 LUT4 in 19 CLBs, 18.9–19.8 MHz depending on the seed |
| `examples/bcd7seg.v` | Four-digit BCD counter with prescaler and multiplexed 7-segment display (registered), pins in `bcd7seg.pcf` (segments on the right, digits at the bottom); the large design | 33 FF, 45 LUT3, 23 LUT4 in 54 of the 64 CLBs (84%), `pack()` places 14 LUT3 in pairs in CLBs. 13.4–14.0 MHz depending on the seed, all runs in at most 4 s. With `PRESCALE=10` 58 CLBs (91%): all runs pass in at most 8 s (without the clock buffers one needs 105 s, up to stage 11 one needed 3 min); with `PRESCALE=50` 61 CLBs (95%): 1 of 17 runs (PD48) runs into the timeout after 300 s with 1 overused wire left, one needs 226 s (real congestion in the debug build; up to stage 11, with the clock over the long.2, 4 of 17 ran into the timeout) |

In VS Code, the general tasks *Arch: Flow ausführen* (run flow) and *Arch: Flow mit nextpnr-GUI* (flow with
nextpnr GUI) work, as do the debug configurations for architectures (Run and Debug). Enter `xc2064` as the
name in each case.

### Regression test

`test/run.sh [design.v …]` synthesizes each example (without arguments all `examples/*.v`), routes it
with the nextpnr default seed and seeds 1–6, with and without PCF, plus once each without PCF in the
packages PD48, PC44 and PG68 (column PCF, `PACKAGES=…` changes the list) and once each with and without PCF
without the clock buffers (`--vopt noclkbuf`, column Seed `noclkbuf`), and checks every run. The Bitstream
column additionally requires that the configuration uses a clock buffer (every example has a clock from a
pad), and none for `noclkbuf`. Lines
`// expected: <cell type> <count>` in the design already check the synthesis (`shiftreg.v` requires 8
`XC2000_FGM`; if the pass drops out, the test fails). The runs execute in parallel, at most
`TEST_JOBS` at a time (default `JOBS`, never more than 10); the rows still appear in a fixed
order. After the runs, `tools/xc2064xnf` writes the XNF netlist for XACT for each design in three versions
(from gates, with `--lut`, with `--iobff`, table *XNF*), and `test/check_xact.py` checks each one: structure,
only symbols from `xc2064db/xnf.py` with their pins, each net with exactly one driver, pads only on buffers,
at most one GCLK and one ACLK, as many storage elements and pads as with `synth_xc2064` (with `--iobff`
also the same number of `INFF`) and a `LOC` for each pin of the PCF. XNFMAP itself only runs in DOSBox (see
[XNF for XACT](#xnf-for-xact-toolsxc2064xnf)). The columns of the runs:

| Column | Check |
|---|---|
| PnR | nextpnr finishes without error within `TIMEOUT` seconds (default 300, router2 has no abort limit). Missed timing alone is not an error (`--timing-allow-fail`) |
| Net | The netlist after routing (`*.pnr.json`, i.e. after `pack()` with input swapping, INIT permutation and constants) is formally equivalent to the RTL |
| Pips | `test/extract_netlist.py` recovers the netlist solely from the occupied Bels and the used pips, i.e. from what a bitstream records. Every input must be connected to the driver that nextpnr's netlist intends, none may have two, and no used pip may be orphaned. The netlist recovered this way must also be equivalent to the RTL. This also covers placement and routing |
| Bitstream | Round trip through the real bitstream: nextpnr writes the configuration as text (`--vopt out=`), `xc2064pack` turns it into an RBT file, `xc2064unpack` and `xc2064pack` once more reproduce it bit-exactly, and `xc2064netlist` recovers a netlist solely from the RBT file (names of ports and registers from the text file), which must be formally equivalent to the RTL. A corrupted LUT bit is caught this way |
| Shirriff | Independent cross-check: Shirriff's decoder (`tools/xc2064shirriff`) reads the RBT file with its own reader and must decode it the same way as the package (see below). `-` without the Python package `quickjs` |
| LCA | `tools/xc2064lca` writes the configuration as LCA for MAKEBITS, and `test/check_xact.py` checks it against the RBT file: exactly one block for each used CLB and each IOB, Base, Config and Equate as decoded, and the pins of each net are connected in the routing graph via the programmed bits, different nets separated (separated at the clock buffers as in the LCA). MAKEBITS itself only runs in DOSBox outside the test (see [Clock buffer inputs](#clock-buffer-inputs-makebits)) |
| Fmax | Lowest frequency of all clocks. With `FMIN=…` (MHz), a value below it is an error |
| Routing | Iterations and runtime of router2, for information only |

The comparison runs in yosys. It reads the RTL with `proc -norom` so that large `case` statements
(7-segment decoder) stay logic, because `equiv` cannot handle a ROM. `equiv_make` pairs the
signals with the same name (ports and registers),
`clk2fflogic` models the clocks with their edge (so `CLKINV` counts too), and `equiv_induct`
proves equality for all input sequences. The models are `yosys/cells_sim.v` and, for the
constant cells that nextpnr created up to stage 3, `test/pnr_cells.v` (since stage 4 constants are
ordinary LUTs). A changed INIT bit, swapped
LUT inputs, an inverted `CLKINV`, an FF instead of a latch, a dropped pip or a LUT input on
the wrong source are each caught.

The round trips check the package against itself: an error that is the same in writing and reading
(e.g. a wrong bit order of the LUTs) would not be noticed there. Therefore Shirriff's decoder from
`external/shirriff-xc2064/html` (`draw.js`, `karnaugh.js`, `parse.js`, `iob.js`, `clb.js`) additionally runs
without a browser in QuickJS (Python package `quickjs`, listed in `.devcontainer/requirements.txt`;
`xc2064db/shirriff.py` provides `window`, `$`, `alert` and `assert`). Per bitstream, the comparison covers:

- the interior of all 64 CLBs: base (F, FG, FGM), inputs of F and G, both truth tables, X, Y, FF
  or latch, set, reset and clock. This is the independent part, because Shirriff reads these bits from the
  bit table in chip layout with his own bit order, the package via the names of the bit map;
- the selected source of the 320 CLB inputs (G position of the crossing) and of the O, T and K muxes of the
  IOBs (index in the list of `iob.js`, for lines also the G position), plus latched inputs. The package took
  these tables over from `clb.js` and `iob.js`; the comparison checks that transfer;
- pips, switch connections and buffers.

The comparison factors out known discrepancies: for the clock, Shirriff distinguishes K and G differently
from XACT (`TEST1.LCA`), so only off, via C (with inversion) or via K or G is compared; in row I he swaps
the matrices 8.1 and 8.2; for base F and FGM he calls the shared output F or M respectively.
His decoder decodes all ten XACT bitstreams (`test/bitstreams.sh`) and all bitstreams of the regression
test the same way as the package. Two cross-checks show that the comparison does find something: Shirriff's
decoding of `TEST1.RBT` against our own of `AND_OR.BIT` yields 95 discrepancies, and two swapped codes in
the table of a CLB input are caught immediately.

```bash
python3 arch/xc2064/tools/xc2064shirriff build/flows/xc2064/test/inreg/pcf-with-seed-default.rbt
```

The comparison does not know the high-impedance state. `test/tristate_split.py` therefore prepares both
netlists: every tristate driver becomes a multiplexer with a fixed 0 or 1 instead of Z, and the comparison
runs for both values. If one netlist drives where the other is high-impedance, this is caught in one of the
two runs. Every `inout` port becomes an output, and whatever reads it reads a new input `<Port>$ext`
instead, i.e. the value that the outside world applies. This also checks the read path via O. A T on the
wrong net, swapped I or O of two bus bits, swapped T and I, or a tristate output without T are each
caught.

Environment variables: `SEEDS="1 2 3"` (in addition to the default seed; empty: only the default seed),
`FREQ`, `FMIN`, `TIMEOUT`, `YOSYS`, `NEXTPNR`. Logs, netlists and the equivalence logs of each run are in
`build/flows/xc2064/test/<design>/`. The script exits with an error if a run fails.

### GUI

The graphics are a schematic of the whole chip with **all lines, Bels and pips**. nextpnr otherwise hides
unused pips; `xc2064.cc` draws them dimmed. After routing, the used ones are highlighted, so that every path
can be followed from the pad through channels, switch matrices and input multiplexers into the LUTs and the
flip-flop. Hovering the mouse over a pip makes the GUI show its name.

The orientation follows the datasheet and die photos: X0Y0 at the top left. In the tiles X1Y1…X9Y9 the
switch matrices 8.1 and 8.2 sit at the top left, to their right the channel above the CLB, below them the
channel to the left of the CLB. The lines in them show the graph from the data:

- **Position:** The lines lie in the order and with the spacing from Shirriff's `draw.js`, at the edge
  with the additional Long Lines.
- **Switch matrices:** A frame around the pins. Each connection of the pattern is a line from pin to pin;
  used ones light up.
- **Single-length segments** end at the frames of the matrices.
- **Fifth vertical line:** Its piece starts at the box of the connection point at the top of the channel,
  runs a short way on the track of local.6 and then bends onto the track of local.5. The piece of the row
  above continues alongside it into the channel.
- **Long Lines and GCLK** run over the full height or width. GCLK comes in at the top as `CLK.AA.O` from
  pad P9, ACLK horizontally at the bottom from pad P43. The clock buffer inputs from lines are boxes in
  the corners: in AA, where `row.A.local.3`/`row.A.long.3` cross the column `col.A.clk` and
  `col.A.local.3`/`col.A.long.3` cross `CLK.AA.O` (for this, `CLK.AA.O` extends down to local.3 in AA), in
  II at `row.I.clk` and at a piece of ACLK at the right end that reaches up to `row.I.long.1`.
- **Repowering buffers** are two triangles tip to tip on the single-length segments at the section
  boundaries (before the channels of rows and columns D and G). They belong to the segment and light up
  with it.
- **PIP boxes** sit at every crossing that has a PIP bit.

The IOBs are drawn as in the datasheet: the pad outside, inside the frame the output driver (triangle
towards the pad) with its multiplexer and the smaller multiplexer for the tristate, next to it the input
driver (triangle pointing inwards). Output, tristate and input run as three lines across the channel
parallel to the edge. As with Shirriff, output and input then bend into a stub parallel to the edge that
crosses the lines of the channel perpendicular to the edge; the depth of the stubs is chosen so that the
pins of an IOB do not cross. `xc2064.cc` reads which crossings get a box from the pips of the chipdb, so
drawing the IOBs needs no table of its own.
Direct connections: on the right edge, X and Y of the CLB to the left run through the edge channel into the
output multiplexer of the first IOB; for the second IOB of the tile below they bend downwards before the
edge channel. At the top and bottom, X runs vertically into the output multiplexer of the second IOB (which
is drawn mirrored for this). The input from the pad runs on its stub at the top to A (branch on the track
of col.x to B), at the bottom to D (branch to C), on the left to B of the edge CLB. At P9 and P43 the input
crosses the clock line (`CLK.AA.O` or `row.I.clk`); the box there is the input of the clock buffer; the
output multiplexer has GCLK or ACLK on the same line as a source. P11 reaches GCLK at `col.A.clk`, P46
reaches ACLK via its stub down to `row.I.clk`.

The input follows Figure 3 of the datasheet: behind the input driver it branches, on the left directly, on
the right via the FF (clock with triangle), both into the input multiplexer, whose output is the line across
the channel. If the IOB is occupied, the multiplexer shows the selected path (`XC2000_INFF`: via the FF). The
clock K comes from outside, next to the IOB, from the clock line of its side, which runs along the outermost
chip edge. Its K mux lies at a corner as a stub on Shirriff's tracks: top `col.I.local.0` to the left of
column I down across the lines of row A, right `row.A.local.5` below the channel of row A, bottom
`col.A.local.5` up across the lines of row I, left `row.I.local.0` below that channel. Each source gets a
box there.

A CLB (grey frame) follows the block diagram in the datasheet, from left to right:

| Column | Contents |
|---|---|
| Inputs | A, B, C, D as rows from the left. A comes from the channel above, D from the channel below, B and C from the channel to the left |
| Combinational logic | Rails Q, D, C, B, A, the multiplexers of the LUT inputs, LUT F, LUT G and FG as a frame around both with the F/G multiplexer (B selects); FGM is the same multiplexer without the frame |
| Distributor | F, FG, G with the multiplexers for set (top), data, clock and reset (bottom) |
| Storage element | D and clock (triangle) on the left, S at the top, R at the bottom, Q on the right |
| Outputs | Rails F, FG, G, Q with the multiplexers X and Y, both out to the right through the channel (PIP boxes on their tracks and Long Lines) |

As in the datasheet, A runs above the logic to the set multiplexer. C, the clock signal K (from long.2 or
GCLK) and D run below the logic to clock and reset. F, FG and G run above the storage element to the outputs,
Q runs around the bottom back to the LUTs. The direct lines of X run up and down the right edge to the pins
of the CLB above or below, Y continues through the channel into the B row of the CLB to the right. No line
runs through a component. In routing, every wire draws its whole line up to the crossings where it can be
switched, including the direct lines and the pad connections. The pip there is just the box, like metal and
switch in the chip. Selecting a wire therefore lights up the whole line. Inside the CLB, pips are a tap
with a dot on the rail. A used pip additionally shows its path through the multiplexer. In FG mode the
multiplexers of F and G, the frame and the F/G multiplexer light up. In the mux mode FGM, F, G and the F/G
multiplexer light up without the frame (two functions), and at F and G only the input multiplexers that its
table needs.

Because nextpnr itself draws with y pointing up, `xc2064.cc` mirrors the graphics. Because nextpnr passes
`drawPip` the canonical wire of a node (which may lie in a neighbouring tile), `local_gfx_id()` looks up the
wire in the pip's tile.

A `--post-route` script with `ctx.writeSVG("chip.svg", "scale=300")` produces an image of the whole chip without the GUI.
The SVG draws in a fixed order, not by state. A dimmed line can therefore cover a used one at the same
position there (FG uses the multiplexers of F and G). The GUI always draws used items on top.

## Data sources and bitstream tools

The path to a real bitstream builds on two submodules in `external/`. Nothing is changed in the submodules
themselves; both are only read.

| Submodule | Commit | Used |
|---|---|---|
| `shirriff-xc2064` ([shirriff/xc2064](https://github.com/shirriff/xc2064)) | `4d35c218` (2021-05-25) | `html/XC2064-def.txt` (name of each of the 11,360 bits), `html/draw.js` (line names and their positions), `html/clb.js` (CLB input muxes), `html/iob.js` (IOBs), `obsolete/test/TEST1.RBT` with `TEST1.LCA` |
| `openxc2064` ([rates37/openxc2064](https://github.com/rates37/openxc2064), MIT) | `db348a02` (2026-10-03) | `bitstream/XACT_comparisons/*.BIT` and `hardware/bitstreams/AND_OR.BIT` (generated with XACT), `possible_connections` in `bitstream/generate_bitstream.py` as a cross-check |

XACT serves only as a black box: MAKEBITS (LCA → bitstream), XDELAY as well as XNFMERGE, XNFPREP, XNFMAP and
MAP2LCA (XNF → unplaced LCA) run without a dongle in a DOSBox outside the repo and provide cross-checks, e.g.
the codes of the clock buffer inputs. The device data of
XACT (.DEV, .DIE, .BSD, .SPD) are not decoded; XACT files are not in the repo.

**Reconciling the two sources** (`python3 -m xc2064db`, see below). The provenance of the openxc2064 data
is not documented there. The comparison shows that it largely builds on Shirriff:

| openxc2064 | Result |
|---|---|
| `pin_planning/XC2064-def.txt` | Copy of Shirriff's file, so no independent confirmation |
| `bitstream/XC2064-spreadsheet.csv` | The same bit map as a 71 × 160 table (`spreadsheet_maker.py`) |
| `possible_connections` | Matches the switch matrix pattern from Shirriff's Magic bits (pins 0–7 there = 1–8 in Shirriff) |
| `src/openxc2064/device/data/xc2064_8x8.json` | Schematic of the simulator with screen coordinates, without reference to bits or Shirriff's names; not used |
| XACT bitstreams | Independent: generated with Xilinx's software. All fit Shirriff's bit map (no programmed bit at an unused position, every CLB mux code known in `clb.js`) |
| `hardware/bitstreams/LUT_TEST.BIT` | Different format (5010 bytes, different header), not read yet; COUNTER, LUT2 and PIN_FIND there are identical to those under `XACT_comparisons` |

So far there are no discrepancies between the sources. As for Shirriff's file: it ends at bit 11,357; bits
11,358 and 11,359 are treated as unused, as in his viewer.

**`xc2064db`** (Python package in `arch/xc2064`) reads the sources. It is the common basis for the
chipdb generator (names and connections) and the bitstream tools (bit map):

| Module | Contents |
|---|---|
| `bitmap` | Type and fields of each bit from `XC2064-def.txt` |
| `lines` | Line names (`col.B.local.1`, `row.C.long.1` …) and their G coordinates. It reads the edges as text from `draw.js` and computes columns and rows B–H the way `initNames()` does there. A PIP entry such as `170G23` is the crossing of two lines |
| `switches` | 154 switch matrices (2 per crossing, none at the corners), pins 1–8, connections from the Magic bits |
| `clbmux` | CLB inputs A–D and K: sources and mux codes, like `generateClbPips()` in `clb.js` |
| `bitstream` | Read and write `.BIT` and `.RBT` |
| `iobmux` | IOBs from `iob.js`: sources and codes of the output and T multiplexers, input pips, the four K muxes of the latched inputs (`kmuxes`), the input muxes of the clock buffers (`clkmuxes`, codes from MAKEBITS) |
| `blocks` | Configuration of the CLBs (LUTs, input selection, FF/latch, clock, set/reset, X/Y), the IOBs (input direct/latched) and the options: bits ↔ fields, XACT's default state |
| `config` | Text format of the configuration: bits → text (`decode`), text → bits (`encode`) |
| `netlist` | Netlist from a bitstream (reverse direction for the formal comparison), function generators as `XC2000_LUT3`, `XC2000_LUT4` (BASE F) or `XC2000_FGM` (BASE FGM) |
| `packages` | Packages PC68, PD48, PC44 and PG68: pin → pad |
| `graph` | Routing graph: segments from the break points at the matrices and the model of the fifth line, connections from PIP, Magic and mux bits. The generator `nextpnr/xc2064_arch_gen.py` builds the tiles from it, `xc2064unpack` checks the bitstreams against it |
| `lca` | Read XACT's `TEST1.LCA` and check it against the decoding and the graph; write a configuration as LCA for MAKEBITS (`write`, `tools/xc2064lca`) |
| `xnf` | Flat yosys netlist → XNF netlist for XNFMAP (`write`, `tools/xc2064xnf`), the yosys script for it (`yosys_script`), reading PCF |
| `shirriff` | Load Shirriff's JavaScript decoder in QuickJS, decode an RBT file with it and compare with our own decoding (`tools/xc2064shirriff`) |

What the data tell us about the original:
- **Switch matrices:** The 98 inner ones have the same pattern with 20 connections, each pin to 5 of the
  other 7. The 56 at the edge have the same pattern without the pins of the missing side.
- **CLB inputs:** A has 6–7 sources, B 10, C 8, D 6–7 and K 2.
- **IOBs:** Output to the pad from 6–9 sources, T from 4 (2 single-length segments and 2 Long Lines of the
  channel parallel to the edge), input onto 5–7 lines. The lines of a pin at the crossings
  (`io1`–`io6`, `x`, `clbl`/`clbr`/`clbw`, the edge lines local.0 and local.5) are part of the IOB and
  not separate routing lines. The code of the T multiplexer also carries the mode: tristate (one
  source selected), driver always on or always off. The four K muxes of the latched inputs (4 bits each,
  6 sources) select a source even without a programmed bit (code 15, like the O muxes); XACT leaves them
  there, except for the top one in `TEST1.RBT` (code 8, P8 is latched).
- **Repowering buffers:** The 158 Bidi bits, which Shirriff does not decode either, carry a G position as
  their name, and it always lies on exactly one single-length segment: 86 vertical (all local.1–5 of every
  column at G 109 and 52, i.e. just before the channels of rows D and G), 72 horizontal (at G 65 and 125,
  before columns D and G). These are the bidirectional buffers at the boundaries of the 9 sections from the
  datasheet. The XACT bitstreams show their direction: for each of the 30 buffers that have a net with its
  driver on one side, the bit is 0 if the buffer points away from the driver downwards or to the right, and
  1 if upwards or to the left, even if there is no sink behind it (otherwise it would drive into the net
  like a second driver). Only buffers with no driver on either side are set inconsistently by XACT.
- **CLB configuration:** 37 bits per CLB, meaning as in Shirriff's `clb.js` with one exception for the
  clock: the bit "CLB AB" selects C; otherwise K applies if the K mux has a source, and G if not, where
  G arrives inverted relative to K, and a latch reverses "CLK Invert". Shirriff confuses K and
  G:NOT here; `TEST1.LCA` (CLK:K, C, C:NOT, G, G:NOT, latches) shows it unambiguously. LUT table: bit i is the
  output for input 1 = i & 1 etc.; for BASE F, B selects (B = 1: table F).
- **Default state:** For an unused CLB, XACT sets exactly `BASE FG`, `Select Latch/FF` and
  `Set-Enable`, for an unused IOB `I PAD/Latched` and the T code "off"; the 8 "Other" options are the
  same in all ten bitstreams (DONE pull-up, readback, `UNknown 2` set). `xc2064pack` fills in everything
  the text does not specify with these values.
- **Coverage:** The package decodes all 8596 used bits: pips, switch matrices, the muxes of CLB,
  IOB and clock buffers, the direction of the buffers, the configuration of the CLBs and IOBs and the
  options. The 14 bits of the clock buffer inputs `CLK.AA.I` and `CLK.II.I` are not used by any bitstream;
  their codes come from MAKEBITS (see [Clock buffer inputs](#clock-buffer-inputs-makebits)).
- **Routing graph:** It contains all 2520 Magic bits and all 1656 PIP bits: 798 PIPs between
  general lines, 8 directional ones from ACLK onto the vertical long.2 (column A: long.4), 448
  output PIPs of X and Y, 353 input PIPs of the IOBs and 49 connection points of the fifth line. In addition
  the 2064 mux sources of the CLB inputs and 642 of the IOB multiplexers (410 output, 232 T), 22 sources of
  the K muxes with the 58 fixed clock inputs of the IOBs and 12 sources of the clock buffer muxes. Not in the
  graph are 8 entries from `iob.js` and the oscillator: 6 crossings with `col.A.io2` at the second pads on
  the left (P13–P23), for which the bit map has no PIP bit and which MAKEBITS cannot program either (those at
  P9 and P11 are inputs of the GCLK buffer, `@aclk_in` at P43 is that of the ACLK buffer), and one source each
  of the K muxes on the right and at the bottom (`col.I.io3`, `row.I.io4`, stubs of unknown origin).
- **Cross-check with XACT:** All 210 routing elements that XACT names in `TEST1.LCA` are in the
  decoding of `TEST1.RBT`. 2 of them are crossings at the top K mux without a bit of their own: XACT names
  `row.A.local.1` and `row.A.local.2`, the decoding gives code 8 = `row.A.local.1` (not checked). 29 are T
  inputs of pads whose driver is always on or always off according to the T code (XACT routes T anyway, the
  multiplexer does not select it). The graph connects the CLB and IOB pins of the nets BC, bc2, BD, bd2, K,
  p1, P3, P9 and q1 exactly as XACT does and keeps all nets separate. XACT itself did not route CB and DB.
  `xc2064unpack` finds all 127 programmed pips and switch connections of `TEST1.RBT` in the graph.
  Base, Config and Equate of all 42 blocks (38 CLBs, 4 IOBs) match the decoding. The package names the
  matrices of row I as XACT does (Shirriff's switch class swaps 8.1 and 8.2 there).
- **Round trip:** All ten XACT bitstreams reproduce themselves bit-exactly through `xc2064unpack` and
  `xc2064pack` (`test/bitstreams.sh`).

**Bitstream format** (XACT's `.BIT` and `.RBT`): a 40-bit header is followed by 160 frames consisting of start
bit `0`, 71 data bits and `111`. Bit i of the bit map is in frame i // 71 at position i % 71. A
programmed bit is 0. The RBT file has 7 text lines in front of this, e.g. `Xilinx LCA TEST1.LCA 2064LPC68`
and `Produced by XACT version 5.1.0`. It writes the header and each frame as one line, and at the end
comes `11111111`. MAKEBITS 5.2.0 writes a different length count into the header (12049 instead of 12045)
and 16 ones at the end; the reader accepts both with a note.

**Text format** (between nextpnr and `xc2064pack`, reverse direction `xc2064unpack`), one line per entry:

```
device XC2064
package PD48                               # package for the RBT header (PC68, PD48, PC44 or PG68)
clb AB BASE:FG F:A:B:C G:A:C:Q LUTF:96 LUTG:E8 X:F Y:G Q:FF SET:A RES:D CLK:K:NOT
iob P8 I:Q                                 # IOB input direct (PAD) or latched (Q, FF in the IOB)
mux AB.A row.A.local.1                     # CLB input and selected source line (or none)
mux P59.O AH.X                             # output mux of an IOB: line, X/Y of a CLB, GCLK or ACLK
mux P59.T col.I.long.2                     # T mux of an IOB: source (tristate), on (driver on) or off
mux P9.K row.A.long.3                      # K mux: clock of the latched inputs at the top (P59 right, P27 bottom, P24 left)
mux CLK.AA.I P9                            # input of the clock buffer GCLK (CLK.II.I: ACLK): line, pad or OSC
pip col.B.local.5:row.B.local.3            # PIP: crossing of two lines
switch AB.8.1 3-8                          # connection of two pins of a switch matrix
bidi 125G6 right                           # repowering buffer: down/right (bit 0), otherwise up/left
bidi auto                                  # direction of all buffers from the routing (xc2064pack)
other DONE pin Pullup/No Pullup 1          # options
bit <Name>                                 # any other programmed bit, by name (no longer occurs)
port P9 clk input                          # (nextpnr) port at the pad, for the way back to the netlist
reg AB ctr[0]                              # (nextpnr) name of the register of a CLB, likewise
reg P8 s1[0]                               # (nextpnr) ... or of a latched input
```

The CLB fields follow XACT's `Config` (with BASE and the truth tables added; F and G name the
selected inputs, not just the used ones). `xc2064unpack` writes every CLB, every IOB, every mux and
all options, plus every programmed bit; the file is lossless. nextpnr writes only what is used;
`xc2064pack` adds XACT's default state and derives the direction of the buffers. Every pip of the chipdb
carries the text-format lines for the routing as extra data (from `xc2064db.graph.cfg`).

```bash
python3 arch/xc2064/tools/xc2064unpack TEST1.RBT -o TEST1.txt   # bitstream -> text (aborts on unknown bits)
python3 arch/xc2064/tools/xc2064pack TEST1.txt -o T.rbt --compare TEST1.RBT   # text -> bitstream, comparison
cd arch/xc2064 && python3 -m xc2064db                            # coverage and cross-checks of the data sources
arch/xc2064/test/bitstreams.sh                                   # everything for all XACT bitstreams and TEST1.RBT
```

### Clock buffer inputs (MAKEBITS)

Shirriff does not decode the input muxes of the two clock buffers, and no XACT bitstream uses a
buffer. Sources and codes therefore come from MAKEBITS (XACT 5.2.0) used as an oracle, only through its
normal inputs and outputs:

1. XACT names the buffer pins `CLK.AA.I`/`CLK.AA.O` (GCLK) and `CLK.II.I`/`CLK.II.O` (ACLK).
   `XDELAY -convert` re-routes the nets of an LCA. One net from each of the 128 CLB outputs and 58 pads into
   each buffer shows through which crossing XACT reaches the buffer, and MAKEBITS turns that into bits.
2. MAKEBITS reads only the G positions of a net (`Program {16G156}`, not the names in `NProgram`) and
   reports locations it cannot program. An LCA with all locations of a rectangle around each buffer
   yields the programmable ones, and because several sources of the same mux are on at once, MAKEBITS
   names all of its pips. One LCA with exactly one of these pips each yields that pip's code.
3. XDELAY routes the crystal oscillator as `OSC.II.O:CLK.II.I`; it does not enter the general routing.

| Mux | Code | Source | XACT | Crossing |
|---|---|---|---|---|
| `CLK.AA.I` (GCLK, bits 0–5) | 63 | `row.A.local.3` (default setting) | `row.A.local.3:CLK.AA.I` | 16G164 |
| | 30 | P11 | `CLK.AA.I:PAD58.I` | 16G149 |
| | 29 | P9 | `CLK.AA.I:PAD1.I` | 16G156 |
| | 27 | `col.A.local.3` | `col.A.local.3:CLK.AA.I` | 8G157 |
| | 23 | `col.A.long.3` | `col.A.long.3:CLK.AA.I` | 11G157 |
| | 15 | `row.A.long.3` | `row.A.long.3:CLK.AA.I` | 16G161 |
| `CLK.II.I` (ACLK, bits 0–7) | 255 | `row.I.local.2` (default setting) | `row.I.local.2:CLK.II.I` | 165G9 |
| | 222 | P46 | `PAD29.I:CLK.II.I` | 168G13 |
| | 221 | `col.I.long.2` | `col.I.long.2:CLK.II.I` | 170G13 |
| | 219 | `col.I.local.2` | `col.I.local.2:CLK.II.I` | 173G13 |
| | 215 | P43 | `CLK.II.I:PAD30.I` | 165G14 |
| | 207 | `row.I.long.1` | `row.I.long.1:CLK.II.I` | 165G12 |
| | 63 | Crystal oscillator (`OSC`, no Bel) | `OSC.II.O:CLK.II.I` | 167G5 |

Code = sum of bit n · 2^n; 1 means not programmed. Bit 5 switches in one of the sources on bits 0–4 (active
at 0, exactly one each); without a programmed bit the default setting applies; the oscillator programs only
bits 6 and 7. So a buffer always drives its clock line; without a clock net it drives from the default
setting. Until then nextpnr had used ACLK (`row.I.clk`) via the PIPs of the long.2 as a free routing path;
in `bcd7seg.v` this resulted, with the new codes, in a net with two drivers. These PIPs are now directional
(ACLK → long.2); XACT accordingly names them `col.D.long.2:CLK.II.O`. None of this has been checked on a
chip (none is available); the codes reflect XACT's own model.

**Cross-check with MAKEBITS:** `tools/xc2064lca` writes a configuration from nextpnr as an LCA file (nets
from the connectivity of the pips, separated at the clock buffers, with the G positions of each element;
per block Base, Config and Equate; pads with XACT's names `PADn`). MAKEBITS turns it into a bitstream that
must match the one from `xc2064pack` bit-exactly:

```bash
python3 arch/xc2064/tools/xc2064lca design.cfg.txt -o DESIGN.LCA   # then in DOSBox: MAKEBITS -B DESIGN < NUL
python3 arch/xc2064/tools/xc2064pack design.cfg.txt -o design.rbt --compare DESIGN.RBT
```

Without DOSBox, the regression test checks the LCA of each run against that run's bitstream (column *LCA*,
see [Regression test](#regression-test)).

Result (2026-10-17) for 44 runs: from the regression test, for each example, the default seed with and
without PCF (with clock buffers), `--vopt noclkbuf` with and without PCF, and the PD48 (40), plus the 4 runs
with clocks on P11 and P46 from stage 12 (`blinky.v` with the clock on P11, `latch_sr.v` with `clk` on P46 and
`en` on P11, with `clk` on P9 and `en` on P11, and without PCF in the PG68). All 44 bitstreams are
bit-identical, in all 11,360 bits: pips, switch connections, muxes (including both clock buffers and GCLK at
the K muxes in `inreg.v`), CLBs with their equations, IOBs, options and the direction of every repowering
buffer. The first comparison had differed only in the buffers: `xc2064pack` left buffers on one side of
which a driven net ends in the default setting, which can point into the net; MAKEBITS points them away
from the driver. `xc2064db.graph.bidi_directions` now does the same.

### XNF for XACT (`tools/xc2064xnf`)

`tools/xc2064xnf` translates a Verilog design into an XNF netlist of the kind that schematic and
synthesis tools wrote for XACT at the time. For this, yosys synthesizes only down to simple gates and FFs
or latches (`xc2064db.xnf.yosys_script`, storage elements as with `synth_xc2064`); the mapping onto CLBs and
IOBs is done by XNFMAP. This allows the mapping of `synth_xc2064` and nextpnr to be compared with Xilinx's.
Only symbols from `XACT\DATA\XLXLGL2K.XNF`, the list of permitted XC2000 symbols, occur (table in
`xc2064db/xnf.py`).

```bash
python3 arch/xc2064/tools/xc2064xnf arch/xc2064/examples/blinky.v -o BLINKY.XNF   # pins from blinky.pcf
python3 arch/xc2064/tools/xc2064xnf design.v --lut -o DESIGNL.XNF   # logic already as LUTs (EQN symbols)
# in DOSBox, all without a dongle:
#   XNFMERGE BLINKY.XNF BLINKY.XFF; XNFPREP BLINKY.XFF BLINKY.XTF; XNFMAP BLINKY.XTF BLINKY.MAP; MAP2LCA BLINKY.MAP BLINKY.LCA
```

Options: `--pcf` (default: `design.pcf` next to `design.v` as with `flow.sh`; the pins become `LOC=Pxx`),
`--top`, `--package`/`--speed` (line `PART`, default `2064PC68-70`), `--json` (keep the yosys netlist;
a JSON netlist also works as input). Clocks from a pad that clock only storage elements run over
GCLK, a second one over ACLK (`--gclk`/`--aclk` fix the input, `--noclkbuf` disables the selection).
`--iobff` puts FFs directly behind an input into the IOB (`INFF`), like `xc2064_iobff`; XNFMAP does not do this by itself.
The regression test writes all three versions (from gates, `--lut`, `--iobff`) for each example and checks
them without XACT (table *XNF*, see [Regression test](#regression-test)).

MAP2LCA writes an unplaced LCA: the blocks are provisionally on AA, AB, … and P2, P3, …, and the pins from the
PCF are in the `.SCP` as `place block`, which APR reads. Checked on 2026-10-18 with XACT 5.2.0: all eight
examples run through without errors in both variants. XNFPREP only gives notes (inverters that occupy a
function of their own; a net with 26 loads in `uart_tx.v`). XNFMAP warns about `rst` because `RST` is a reserved
block name, and then calls the IOB `RST_I`. In the LCA all special cases are correct: negative edge
`CLK:K:NOT`, asynchronous set/reset `SET:A RES:D`, latch `Q:LATCH` with the enable via ACLK, tristate
`BUF:TRI` with `oe_n` directly on T (XNFPREP cancels out the two inverters), bus `I:PAD BUF:TRI`, with `--iobff`
`I:Q` and GCLK at the K of the IOBs. Occupied CLBs:

| Example | XNFMAP from gates | XNFMAP with `--lut` | nextpnr (`flow.sh`, SEED=1) |
|---|---|---|---|
| `blinky.v` | 29 | 20 | 22 |
| `ampel.v` | 16 | 19 | 20 |
| `bcd7seg.v` | 64 | 53 | 54 |
| `inreg.v` | 8, with `--iobff` 4 | 8 | 8 |
| `latch_sr.v` | 4 | 4 | 4 |
| `shiftreg.v` | 17 | 16 | 8 (FGM) |
| `tristate.v` | 8 | 12 | 8 |
| `uart_tx.v` | 56 | 52 | 47 |

For `inreg.v` with `--iobff`, XNFMAP gets by with 4 CLBs because it puts the edge detection `s1 & ~s2` into the
G generator of the CLB with the FF of `s2` (`X:Q Y:G`, `G=(A*~Q)`); nextpnr occupies 8. XNFMAP does not use
the mux mode FGM for `shiftreg.v`.

## Development stages

- **Latched inputs on `inout` ports** (`XC2000_IOBUF` with FF in the input): XACT can do this; so far the
  model only moves pure inputs into the IOB.
- **Search deeper for FGM**: so far `xc2064_fgm` only merges the D LUT with LUTs directly in front of it.
  Cuts across several levels (or FGM already before `abc`) would find more cases.
- **Real bitstream**: [`XC2064-def.txt`](https://github.com/shirriff/xc2064) describes all 11,360
  configuration bits (LUT contents, IOB options, PIPs, switch matrices). For loadable bitstreams the PIPs of
  the model must correspond exactly to the PIPs of the original. That is why the routing graph is built from
  this data, with Shirriff's line names. The bitstream is then generated, as for iCE40, ECP5 and
  GateMate, in two steps (implemented in stage 5, see [Bitstream](#bitstream)):
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

  Stages:
  1. done: data package `xc2064db`, `xc2064unpack` at bit level, test with the XACT bitstreams (see
     [Data sources](#data-sources-and-bitstream-tools))
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
     [Clock buffer inputs](#clock-buffer-inputs-makebits)): `iobmux.clkmuxes` with 6 or 7 sources, all of them
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
     MAKEBITS (see [Clock buffer inputs](#clock-buffer-inputs-makebits)); `xc2064pack --compare` compares
     bit-exactly for this purpose

  Open on the way to a loaded chip (all of it needs a real XC2064): the first attempt with the
  STM32 loader (D/P pin), and the edge of the IOB FF (rising according to the Data Book) as well as Shirriff's
  K mux codes. The clock buffer codes come from XACT's model, not from the chip.

  After every stage, `test/run.sh` must pass for all examples (Net, Pips and, since stage 5, Bitstream). The
  GUI keeps CLB and IOBs in datasheet style; only the channels follow the line layout from Shirriff.
  Further prior work: [JohnDMcMaster/project2064](https://github.com/JohnDMcMaster/project2064).
