# Cross-checks with XACT

Xilinx's own software, XACT 5.2.0, runs without a dongle in a DOSBox outside the repo and serves only as a
black box (see [Data sources](data-sources.md#submodules)): MAKEBITS supplies the codes of the clock buffer
inputs and a bit-exact cross-check for `xc2064pack`, XNFMAP and MAP2LCA a comparison for the mapping onto CLBs.

## Clock buffer inputs (MAKEBITS)

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
see [Regression test](testing.md)).

Result (2026-10-17) for 44 runs: from the regression test, for each example, the default seed with and
without PCF (with clock buffers), `--vopt noclkbuf` with and without PCF, and the PD48 (40), plus the 4 runs
with clocks on P11 and P46 from [stage 12](development-stages.md#stages) (`blinky.v` with the clock on P11, `latch_sr.v` with `clk` on P46 and
`en` on P11, with `clk` on P9 and `en` on P11, and without PCF in the PG68). All 44 bitstreams are
bit-identical, in all 11,360 bits: pips, switch connections, muxes (including both clock buffers and GCLK at
the K muxes in `inreg.v`), CLBs with their equations, IOBs, options and the direction of every repowering
buffer. The first comparison had differed only in the buffers: `xc2064pack` left buffers on one side of
which a driven net ends in the default setting, which can point into the net; MAKEBITS points them away
from the driver. `xc2064db.graph.bidi_directions` now does the same.

## XNF for XACT (`tools/xc2064xnf`)

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
them without XACT (table *XNF*, see [Regression test](testing.md)).

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
