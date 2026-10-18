# Bitstream

From a routed design, nextpnr writes the configuration as text (`--vopt out=`), and `tools/xc2064pack`
turns it into a bitstream in XACT's RBT or BIT format. The reverse direction, `tools/xc2064unpack`, turns
real bitstreams back into text. None of the generated bitstreams has been loaded onto a real chip yet
(see [Development stages](development-stages.md#open-items)).

## Generating a bitstream

```bash
arch/xc2064/flow.sh arch/xc2064/examples/blinky.v --vopt out=build/flows/xc2064/blinky.cfg.txt
python3 arch/xc2064/tools/xc2064pack build/flows/xc2064/blinky.cfg.txt -o build/flows/xc2064/blinky.rbt
python3 arch/xc2064/tools/xc2064unpack build/flows/xc2064/blinky.rbt -o blinky.txt     # reverse direction, as text
python3 arch/xc2064/tools/xc2064netlist build/flows/xc2064/blinky.rbt --meta build/flows/xc2064/blinky.cfg.txt -o blinky.bit.v
```

`xc2064pack` carries the package from the text file into the RBT header (`2064PD48`, `2064PC44`, …). The RBT
file has exactly XACT's layout (7 text lines, header, 160 frames, `11111111`, CRLF), for the STM32 loader from
[dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026); `-o file.bit` writes the binary
form instead.

## Bitstream format

XACT's `.BIT` and `.RBT`: a 40-bit header is followed by 160 frames consisting of start
bit `0`, 71 data bits and `111`. Bit i of the bit map is in frame i // 71 at position i % 71. A
programmed bit is 0. The RBT file has 7 text lines in front of this, e.g. `Xilinx LCA TEST1.LCA 2064LPC68`
and `Produced by XACT version 5.1.0`. It writes the header and each frame as one line, and at the end
comes `11111111`. MAKEBITS 5.2.0 writes a different length count into the header (12049 instead of 12045)
and 16 ones at the end; the reader accepts both with a note.

## Text format

The text format (between nextpnr and `xc2064pack`, reverse direction `xc2064unpack`), one line per entry:

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

## Tools

```bash
python3 arch/xc2064/tools/xc2064unpack TEST1.RBT -o TEST1.txt   # bitstream -> text (aborts on unknown bits)
python3 arch/xc2064/tools/xc2064pack TEST1.txt -o T.rbt --compare TEST1.RBT   # text -> bitstream, comparison
cd arch/xc2064 && python3 -m xc2064db                            # coverage and cross-checks of the data sources
arch/xc2064/test/bitstreams.sh                                   # everything for all XACT bitstreams and TEST1.RBT
```
