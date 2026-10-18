# Data sources

## References

- XC2000 datasheet
- Ken Shirriff, [Reverse-engineering the first FPGA chip, the XC2064](https://www.righto.com/2020/09/reverse-engineering-first-fpga-chip.html)
- his bitstream decoder [shirriff/xc2064](https://github.com/shirriff/xc2064), whose `clb.js` and `iob.js`
  supplied the input multiplexers of the CLBs, the options of the storage element, the pad table and the
  multiplexers and PIPs of the IOBs; the decoder itself runs without a browser as a cross-check
  (`tools/xc2064shirriff`, see [Testing](testing.md#cross-check-with-shirriffs-decoder))
- [rates37/openxc2064](https://github.com/rates37/openxc2064) with bitstreams from Xilinx's XACT
- Xilinx *The Programmable Logic Data Book* 1994 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1994_Xilinx_Programmable_Logic_Data_Book.pdf)),
  XC2000 section pp. 2-216 to 2-222: component availability and the timing tables of CLB and IOB (-70, -100, -130)
- the same from 1993 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1993_Xilinx_Programmable_Logic_Data_Book.pdf)),
  pp. 2-208 to 2-214: the same tables with -50, -70 and -100
- `MAKEBITS` from Xilinx XACT 5.2.0 as a black box (in DOSBox, outside the repo): codes of the
  clock buffer inputs and cross-check for `xc2064pack` (see [Clock buffer inputs](xact.md#clock-buffer-inputs-makebits));
  `XNFMAP` and `MAP2LCA` for comparing the mapping onto CLBs (see [XNF for XACT](xact.md#xnf-for-xact-toolsxc2064xnf))
- further prior work: [JohnDMcMaster/project2064](https://github.com/JohnDMcMaster/project2064)

## Submodules

The path to a real [bitstream](bitstream.md) builds on two submodules in `external/`. Nothing is changed in
the submodules themselves; both are only read.

| Submodule | Commit | Used |
|---|---|---|
| `shirriff-xc2064` ([shirriff/xc2064](https://github.com/shirriff/xc2064)) | `4d35c218` (2021-05-25) | `html/XC2064-def.txt` (name of each of the 11,360 bits), `html/draw.js` (line names and their positions), `html/clb.js` (CLB input muxes), `html/iob.js` (IOBs), `obsolete/test/TEST1.RBT` with `TEST1.LCA` |
| `openxc2064` ([rates37/openxc2064](https://github.com/rates37/openxc2064), MIT) | `db348a02` (2026-10-03) | `bitstream/XACT_comparisons/*.BIT` and `hardware/bitstreams/AND_OR.BIT` (generated with XACT), `possible_connections` in `bitstream/generate_bitstream.py` as a cross-check |

XACT serves only as a black box: MAKEBITS (LCA → bitstream), XDELAY as well as XNFMERGE, XNFPREP, XNFMAP and
MAP2LCA (XNF → unplaced LCA) run without a dongle in a DOSBox outside the repo and provide cross-checks, e.g.
the codes of the clock buffer inputs. The device data of
XACT (.DEV, .DIE, .BSD, .SPD) are not decoded; XACT files are not in the repo.

## Reconciling the two sources

The check `python3 -m xc2064db` (see [Bitstream tools](bitstream.md#tools)) reconciles the two sources. The provenance of the openxc2064 data
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

## The `xc2064db` package

`xc2064db` (Python package in `arch/xc2064`) reads the sources. It is the common basis for the
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

## What the data tell us about the original

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
  their codes come from MAKEBITS (see [Clock buffer inputs](xact.md#clock-buffer-inputs-makebits)).
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
