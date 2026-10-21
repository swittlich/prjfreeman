# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
# Chip database for a model of the Xilinx XC2064 (1985, the first FPGA) as a Himbächel uarch.
#
# References: XC2000 datasheet; Ken Shirriff's reverse engineering (github.com/shirriff/xc2064, as the
# submodule external/shirriff-xc2064) with the bit map XC2064-def.txt, the line names (draw.js), the
# CLB input muxes (clb.js) and the IOB muxes (iob.js). The package xc2064db (arch/xc2064/xc2064db) reads
# this data; the routing graph is built from xc2064db.graph, each pip there corresponds to one bit or
# one mux code of the original.
#
# Grid (x, y; y downwards): 8x8 CLBs at x, y = 1..8 and an IO ring at 0 and 9. Shirriff's 9x9
# tiles AA..II (row, column) correspond to x = column, y = row = 1..9: each contains the channels
# above and to the left of its CLB and, at their crossing, two switch matrices (8.1, 8.2). The 9th column/row
# (I) contains only routing and pads, the tiles x = 0 and y = 0 the pads on the left and at the top.
#
#   CLB (according to the decoder):
#     Inputs A, B, C, D, clock K; outputs X, Y
#     F, G  : one function of 3 variables each; input 1 from {A, B}, 2 from {B, C}, 3 from {C, D, Q}
#     FG    : F and G together as one function of 4 variables, B selects between them
#     FGM   : the same with different inputs for F and G (mux mode, Data Book "Option 3")
#     FF    : flip-flop or latch; data from F (or FG); clock from K, C or G (invertible);
#             asynchronous set from A or F, asynchronous reset from D or G
#     X, Y  : each from Q, F or G
#   Routing (xc2064db.graph):
#     Channels:       vertical local.1-4 (through the matrices), the fifth line (local.5, offset, with one
#                     connection point per row), 2 Long Lines and GCLK; horizontal 4 single-length segments
#                     and one Long Line, at the edge 4 single-length segments and 2 Long Lines
#     Switch matrix:  2 per crossing, 8 pins, connections from the Magic bits (20 inside, 10 at the edge)
#     CLB inputs:     all sources from clb.js (A 6-7, B 10, C 8, D 6-7, K 2)
#     Outputs:        X (row io6) and Y (row y) via their PIP bits into the channel on the right, X hard-wired
#                     to A/B of the CLB below and C/D of the CLB above, Y hard-wired to B of the CLB on the right
#     Clock:          GCLK (col.*.clk) onto B and K, ACLK (row.I.clk) via the vertical long.2 onto K
#     IOBs (iob.js):  O mux (lines, X/Y of the edge CLB, GCLK at P9) and T mux (2 single-length segments, 2 Long
#                     Lines; buffer off/on is configuration, not a pip), I via PIP bits onto the lines of
#                     both channels at the pad and hard-wired to the inputs of the edge CLB
#                     Clock input K (latched input) hard-wired to the clock line IOCLK of its side, which a
#                     K mux at the corner feeds from the edge channel (top/right in AI, bottom/left in IA)
#     Clock buffers:  input muxes CLK.AA.I (GCLK: P9, P11, 4 edge lines) and CLK.II.I (ACLK: P43, P46,
#                     4 edge lines) with codes from MAKEBITS; pips from lines in AA or II, from pads at the pad
#     Constants:      no line (as in the original); pack() folds them into LUT contents or inserts a LUT
#   Repowering buffers at the section boundaries are not pips: a buffer is never off, its direction follows
#   from the routing (xc2064db.graph.bidi_bit).
#   Timing: CLB and IOB from the Data Books 1993 and 1994 (speed grades -50, -70, -100, -130), interconnect
#   as an RC model as in the datasheet (Interconnect Performance), see DATABOOK and set_timings().
from os import path
import re
import sys
sys.path.append(path.join(path.dirname(__file__), "../.."))
from himbaechel_dbgen.chip import *

ARCH_DIR = path.dirname(path.dirname(path.realpath(__file__)))
sys.path.insert(0, ARCH_DIR)
from xc2064db.graph import Graph  # noqa: E402
from xc2064db import packages  # noqa: E402

N_CLB = 8
X = N_CLB + 2
Y = N_CLB + 2
LAST = N_CLB + 1           # index of the 9th switch matrix column/row
LETTERS = "ABCDEFGHI"

# Pads as in Shirriff's iob.js: (pin, tile row+column, connection direction)
PADS = [
    ("P9", "AA", "topleft"), ("P8", "AB", "topright"), ("P7", "AB", "topleft"), ("P6", "AC", "topright"),
    ("P5", "AC", "topleft"), ("P4", "AD", "topright"), ("P3", "AD", "topleft"), ("P2", "AE", "topright"),
    ("P68", "AE", "topleft"), ("P67", "AF", "topright"), ("P66", "AF", "topleft"), ("P65", "AG", "topright"),
    ("P64", "AG", "topleft"), ("P63", "AH", "topright"), ("P62", "AH", "topleft"), ("P61", "AI", "topright"),
    ("P59", "BI", "rightlower"), ("P58", "BI", "rightupper"), ("P57", "CI", "rightlower"),
    ("P56", "CI", "rightupper"), ("P55", "DI", "rightlower"), ("P54", "DI", "rightupper"),
    ("P53", "EI", "rightlower"), ("P51", "FI", "rightlower"), ("P50", "FI", "rightupper"),
    ("P49", "GI", "rightlower"), ("P48", "GI", "rightupper"), ("P47", "HI", "rightlower"),
    ("P46", "HI", "rightupper"),
    ("P43", "II", "bottomright"), ("P42", "IH", "bottomleft"), ("P41", "IH", "bottomright"),
    ("P40", "IG", "bottomleft"), ("P39", "IG", "bottomright"), ("P38", "IF", "bottomleft"),
    ("P37", "IF", "bottomright"), ("P36", "IE", "bottomleft"), ("P34", "IE", "bottomright"),
    ("P33", "ID", "bottomleft"), ("P32", "ID", "bottomright"), ("P31", "IC", "bottomleft"),
    ("P30", "IC", "bottomright"), ("P29", "IB", "bottomleft"), ("P28", "IB", "bottomright"),
    ("P27", "IA", "bottomleft"),
    ("P24", "HA", "leftupper"), ("P23", "HA", "leftlower"), ("P22", "GA", "leftupper"),
    ("P21", "GA", "leftlower"), ("P20", "FA", "leftupper"), ("P19", "FA", "leftlower"),
    ("P17", "EA", "leftlower"), ("P16", "DA", "leftupper"), ("P15", "DA", "leftlower"),
    ("P14", "CA", "leftupper"), ("P13", "CA", "leftlower"), ("P12", "BA", "leftupper"),
    ("P11", "BA", "leftlower"),
]


def pad_info(pin, tile, style):
    """Tile (x, y), z and side of a pad in the model grid; z = 1 for the second pad of a tile
    ("topright", "rightlower", ...)"""
    r, c = LETTERS.index(tile[0]) + 1, LETTERS.index(tile[1]) + 1
    z = 1 if style in ("topright", "bottomright", "rightlower", "leftlower") else 0
    if style.startswith("top"):
        side, x, y = "T", c, 0
    elif style.startswith("bottom"):
        side, x, y = "B", c, LAST
    elif style.startswith("right"):
        side, x, y = "R", LAST, r
    else:
        side, x, y = "L", 0, r
    return dict(pin=pin, x=x, y=y, z=z, side=side)


PAD_INFO = [pad_info(*p) for p in PADS]


def is_clb(x, y):
    return 1 <= x <= N_CLB and 1 <= y <= N_CLB


def has_sm(x, y):
    return 1 <= x <= LAST and 1 <= y <= LAST


def tile_xy(t):
    """Tile 'BC' (row B, column C) -> (x, y); '@' is the pad row at the top or on the left (0)"""
    return ord(t[1]) - ord("@"), ord(t[0]) - ord("@")


def tile_name(x, y):
    return chr(ord("@") + y) + chr(ord("@") + x)


PAD_BY_PIN = {p["pin"]: p for p in PAD_INFO}
PAD_SIDE = {p[0]: p[2][0].upper() for p in PADS}  # T, B, L, R
PAD_IN = {pin + ".I" for pin in PAD_BY_PIN}  # inputs of the pads (nodes of the graph)


# --- Wire names ---------------------------------------------------------------------------------
REL = {(0, 0): "", (1, 0): "_R", (-1, 0): "_L", (0, -1): "_U", (0, 1): "_D", (-1, 1): "_LD", (1, -1): "_RU"}


def wire_name(node, t):
    """Name of the wire of graph node node in tile t. Vertical lines V<k>, horizontal ones H<k>,
    Long Lines VL<k>/HL<k>; suffix _U/_D/_L/_R for the piece in the neighbouring tile (above, below, left,
    right). CLB pins are named like the pin, X/Y of the neighbouring CLBs XT (X above), XB (X below), YL (Y left)."""
    if node in ("GCLK", "ACLK"):
        return node
    if node.startswith("IOCLK."):  # clock line of the latched inputs of one side
        return "IOCLK_" + node[-1]
    m = re.fullmatch(r"(P\d+)\.([IOTK])", node)
    if m:  # IOB: in its own tile the Bel wires (Bel pin I = XACT .O), in the CLB the direct input
        p = PAD_BY_PIN[m[1]]
        if tile_xy(t) == (p["x"], p["y"]):
            return "IO%d_%s" % (p["z"], {"O": "I", "I": "O", "T": "T", "K": "K"}[m[2]])
        if m[2] != "I":
            raise ValueError("%s outside the pad tile" % node)
        return "P" + PAD_SIDE[m[1]]
    m = re.fullmatch(r"([A-H])([A-H])\.([ABCDKXY])", node)
    if m:
        d = (ord(m[2]) - ord(t[1]), ord(m[1]) - ord(t[0]))
        if d == (0, 0):
            return m[3]
        return {("X", 0, -1): "XT", ("X", 0, 1): "XB", ("Y", -1, 0): "YL"}[(m[3],) + d]
    m = re.fullmatch(r"(col|row)\.([A-I])\.(local|long)\.(\d)(?:@([A-I]))?", node)
    if not m:
        raise ValueError("unknown node %s" % node)
    kind, letter, lk, k, seg = m.groups()
    prefix = ("V" if kind == "col" else "H") + ("L" if lk == "long" else "") + k
    if kind == "col":
        d = (ord(letter) - ord(t[1]), (ord(seg) - ord(t[0])) if seg else 0)
    else:
        d = ((ord(seg) - ord(t[1])) if seg else 0, ord(letter) - ord(t[0]))
    return prefix + REL[d]


def place(cn):
    """Tile in which the pip of a connection lies"""
    if cn.kind in ("iobo", "iobt"):  # IOB: in the tile of the pad
        p = PAD_BY_PIN[cn.b.split(".")[0]]
        return tile_name(p["x"], p["y"])
    if cn.kind == "clkbuf" and cn.a not in PAD_IN:  # clock buffer from a line: at its corner
        return "AA" if cn.b == "GCLK" else "II"
    if cn.kind in ("iobi", "clkbuf"):
        p = PAD_BY_PIN[cn.a.split(".")[0]]
        return tile_name(p["x"], p["y"])
    if cn.kind == "iobkin":  # clock input of an IOB on the line of its side
        p = PAD_BY_PIN[cn.b.split(".")[0]]
        return tile_name(p["x"], p["y"])
    if cn.kind == "iobk":  # K mux: top and right at the top-right corner, bottom and left at the bottom-left one
        return "AI" if cn.b[-1] in "TR" else "IA"
    if cn.kind == "mux":
        return cn.b[:2]
    if cn.kind == "out":
        return cn.a[:2]
    if cn.kind == "switch":
        return cn.name[:2]
    if cn.kind == "junction":
        return cn.b.split("@")[1] + cn.b.split(".")[1]
    col, row = cn.name.split(":")
    return row.split(".")[1] + col.split(".")[1]


def timing_class(cn):
    """Pip class: SM (switch matrix) and PIP (PIP bit) are pass transistors, INMUX the input muxes of
    CLB and IOB, GCLK the clock buffer"""
    if cn.kind == "switch":
        return "SM"
    if cn.kind in ("mux", "iobo", "iobt", "iobk"):
        return "INMUX"
    if cn.kind == "clkbuf":
        return "GCLK"
    if cn.kind == "iobkin":
        return "LOCAL"
    return "PIP"


def node_class(node):
    """Node class for the RC model: single-length segment, Long Line (also the clock line of a side for the
    latched inputs), clock net; none for pins"""
    if node in ("GCLK", "ACLK"):
        return "CLKNET"
    if node.startswith("IOCLK."):
        return "LONG"
    m = re.fullmatch(r"(col|row)\.[A-I]\.(local|long)\.\d(?:@[A-I])?", node)
    return ("LONG" if m[2] == "long" else "SEG") if m else ""


PIP_CFG, PIP_CLKBUF = 1, 2  # kind of a pip's extra data


@dataclass
class PipExtra(BBAStruct):
    """Extra data of a pip from the graph: the line in the text format (xc2064db/config.py) that
    programs it (nextpnr --vopt out=), and the kind (clock buffer input: blocked with --vopt noclkbuf)"""
    cfg: IdString
    kind: int

    def serialise_lists(self, context: str, bba: BBAWriter):
        pass

    def serialise(self, context: str, bba: BBAWriter):
        bba.u32(self.cfg.index)
        bba.u32(self.kind)


class Builder:
    def __init__(self, ch):
        self.ch = ch
        self.graph = Graph()
        self.wires = {}  # (x, y) -> {name: type}
        self.pips = {}  # (x, y) -> {(src, dst): class}
        self.pip_cfg = {}  # (x, y, src, dst) -> (text line, kind)
        self.node_wires = {}  # node -> [(x, y, name)]

    def wire(self, xy, name, typ):
        """Create a wire; ROUTING (from the graph) gives way to a more specific type (CLB_IN, ...)"""
        old = self.wires.setdefault(xy, {}).get(name)
        if old not in (None, "ROUTING", typ) and typ != "ROUTING":
            raise ValueError("wire %s in %s with two types %s, %s" % (name, xy, old, typ))
        if old in (None, "ROUTING"):
            self.wires[xy][name] = typ

    def node(self, node, xy, name):
        lst = self.node_wires.setdefault(node, [])
        if (xy[0], xy[1], name) not in lst:
            lst.append((xy[0], xy[1], name))
        owner = self.wire_owner.setdefault((xy, name), node)
        if owner != node:
            raise ValueError("wire %s in %s belongs to %s and %s" % (name, xy, owner, node))

    def pip(self, xy, src, dst, cls):
        self.pips.setdefault(xy, {})[(src, dst)] = cls

    def routing(self):
        self.wire_owner = {}
        for cn in self.graph.conns:
            t = place(cn)
            xy = tile_xy(t)
            a, b = wire_name(cn.a, t) if not self.direct_xy(cn) else self.direct_xy(cn), wire_name(cn.b, t)
            for n, w in ((cn.a, a), (cn.b, b)):
                self.wire(xy, w, "ROUTING")
                self.node(n, xy, w)
            cls = timing_class(cn)
            cfg = (self.graph.cfg(cn), PIP_CLKBUF if cn.kind == "clkbuf" else PIP_CFG)
            self.pip(xy, a, b, cls)
            if cfg[0] is not None:  # hard-wired connection (iobkin): no line in the text format
                self.pip_cfg[xy + (a, b)] = cfg
            if cn.kind in ("pip", "switch", "junction"):  # pass transistor: both directions
                self.pip(xy, b, a, cls)
                self.pip_cfg[xy + (b, a)] = cfg

    @staticmethod
    def direct_xy(cn):
        """X/Y of an edge CLB directly in the output mux of an IOB: wire IO<z>_X/Y in the pad tile"""
        if cn.kind == "iobo" and re.fullmatch(r"[A-H][A-H]\.[XY]", cn.a):
            return "IO%d_%s" % (PAD_BY_PIN[cn.b.split(".")[0]]["z"], cn.a[-1])
        return None

    def clb(self, x, y):
        """Bels and internal pips of a CLB (LOCAL: part of the logic delay, XYDRV: output driver)"""
        xy = (x, y)
        for p in "ABCDK":
            self.wire(xy, p, "CLB_IN")
        for o in "XY":
            self.wire(xy, o, "CLB_OUT")
        self.wire(xy, "Q", "FF_Q")
        lut_in = [("A", "B"), ("B", "C"), ("C", "D", "Q")]
        self.bels = getattr(self, "bels", {})
        bels = self.bels.setdefault(xy, [])
        for name, z, n in (("F", 0, 3), ("G", 1, 3), ("FG", 2, 4)):
            pins = []
            for i in range(n):
                w = "%s_I%d" % (name, i)
                self.wire(xy, w, "LUT_IN")
                pins.append(("I[%d]" % i, w, PinType.INPUT))
                for s in (lut_in[i] if i < 3 else ("B",)):  # FG: I[3] = B selects between F and G
                    self.pip(xy, s, w, "LOCAL")
            self.wire(xy, "%s_O" % name, "LUT_OUT")
            pins.append(("O", "%s_O" % name, PinType.OUTPUT))
            bels.append((name, "LUT%d" % n, z, pins))
        # FGM (mux mode): F and G with their own inputs, B selects. The same hardware as FG, only the input muxes
        # of F and G are set differently; the Bel therefore uses the wires of F, G and FG.
        bels.append(("FGM", "FGM", 4, [("%s[%d]" % (h, i), "%s_I%d" % (h, i), PinType.INPUT)
                                       for h in "FG" for i in range(3)]
                     + [("S", "FG_I3", PinType.INPUT), ("O", "FG_O", PinType.OUTPUT)]))
        for w in ("FF_D", "FF_CLK", "FF_S", "FF_R"):
            self.wire(xy, w, "FF_IN")
        for s, d in (("F_O", "FF_D"), ("FG_O", "FF_D"),
                     ("K", "FF_CLK"),
                     ("A", "FF_S"), ("F_O", "FF_S"), ("FG_O", "FF_S"),
                     ("D", "FF_R"), ("G_O", "FF_R"), ("FG_O", "FF_R")):
            # set/reset directly from A or D: T_RIO instead of T_RLO (pip class SRDIR, see clb_timing)
            self.pip(xy, s, d, "SRDIR" if (s, d) in (("A", "FF_S"), ("D", "FF_R")) else "LOCAL")
        for s, cls in (("C", "CLKC"), ("G_O", "CLKG"), ("FG_O", "CLKG")):  # clock via C or G
            self.pip(xy, s, "FF_CLK", cls)
        bels.append(("FF", "DFF", 3, [("D", "FF_D", PinType.INPUT), ("CLK", "FF_CLK", PinType.INPUT),
                                     ("S", "FF_S", PinType.INPUT), ("R", "FF_R", PinType.INPUT),
                                     ("Q", "Q", PinType.OUTPUT)]))
        for o in "XY":
            for s in ("F_O", "G_O", "FG_O", "Q"):
                self.pip(xy, s, o, "XYDRV")

    def iob(self, p):
        """IOB pad: Bel and wires. Its muxes and pips come from the graph (iob.js, routing()); the
        mode on/off/tristate follows from the cell type (pack() in xc2064.cc), T therefore has no constants."""
        xy, z = (p["x"], p["y"]), p["z"]
        for sfx, typ in (("I", "IO_I"), ("T", "IO_T"), ("O", "IO_O"), ("K", "IO_K"), ("PAD", "IO_PAD")):
            self.wire(xy, "IO%d_%s" % (z, sfx), typ)
        self.bels = getattr(self, "bels", {})
        self.bels.setdefault(xy, []).append((p["pin"], "IOB", z, [
            ("I", "IO%d_I" % z, PinType.INPUT), ("T", "IO%d_T" % z, PinType.INPUT),
            ("O", "IO%d_O" % z, PinType.OUTPUT), ("K", "IO%d_K" % z, PinType.INPUT),
            ("PAD", "IO%d_PAD" % z, PinType.INOUT)]))

    def build(self):
        ch = self.ch
        self.routing()
        for x in range(X):
            for y in range(Y):
                if is_clb(x, y):
                    self.clb(x, y)
        for p in PAD_INFO:
            self.iob(p)
        for x in range(X):
            for y in range(Y):
                xy = (x, y)
                tt = ch.create_tile_type("T_X%dY%d" % (x, y))
                for name, typ in sorted(self.wires.get(xy, {}).items()):
                    w = tt.create_wire(name, typ)
                    node = self.wire_owner.get((xy, name))
                    if node and len(self.node_wires[node]) == 1 and node_class(node):  # node of a single wire
                        w.timing_idx = ch.timing.node_class_idx(node_class(node))
                for name, typ, z, pins in self.bels.get(xy, []):
                    bel = tt.create_bel(name, typ, z=z)
                    for pin, w, d in pins:
                        tt.add_bel_pin(bel, pin, w, d)
                for (src, dst), cls in sorted(self.pips.get(xy, {}).items()):
                    pp = tt.create_pip(src, dst, timing_class=cls)
                    cfg = self.pip_cfg.get(xy + (src, dst))
                    if cfg:
                        pp.extra_data = PipExtra(ch.strs.id(cfg[0]), cfg[1])
                if has_sm(x, y) and not (x in (1, LAST) and y in (1, LAST)):  # first: index = matrix 8.1/8.2
                    tt.create_group("SM0", "SWITCHBOX")
                    tt.create_group("SM1", "SWITCHBOX")
                if is_clb(x, y):
                    tt.create_group("CLB", "CLB_FRAME")  # GUI only: frame of the CLB
                ch.set_tile_type(x, y, "T_X%dY%d" % (x, y))
        for node, wires in self.node_wires.items():
            if len(wires) > 1:
                ch.add_node([NodeWire(x, y, w) for x, y, w in wires], timing_class=node_class(node))


# --- Timing ----------------------------------------------------------------------------------------
# Values from the Xilinx Programmable Logic Data Book, XC2000 "CLB Switching Characteristic Guidelines" and
# "IOB Switching Guidelines", in ns, maximum values. The speed grade is the toggle rate of an FF in MHz. -50
# from the 1993 Data Book (pp. 2-213, 2-214; the XC2064 in the PD48 was only available in this grade, p. 2-208),
# -130 from the 1994 one (pp. 2-221, 2-222). -70 and -100 are the same in both.
DATABOOK = {
    #       T_ILO T_QLO T_CKO T_ICK T_CCO T_CIO T_PID T_OP T_THZ T_TON T_LI T_PL T_LP T_ITO T_RIO T_RLO
    "50": (15.0, 8.0, 15.0, 9.0, 19.0, 27.0, 8.0, 12.0, 20.0, 20.0, 15.0, 8.0, 0.0, 20.0, 22.0, 28.0),
    "70": (10.0, 6.0, 10.0, 7.0, 13.0, 20.0, 6.0, 9.0, 15.0, 15.0, 11.0, 6.0, 0.0, 14.0, 16.0, 21.0),
    "100": (8.0, 6.0, 7.0, 6.0, 9.0, 13.0, 4.0, 7.0, 11.0, 13.0, 8.0, 4.0, 0.0, 10.0, 10.0, 14.0),
    "130": (5.5, 3.7, 7.0, 2.5, 7.0, 13.0, 3.5, 5.5, 7.0, 11.0, 7.5, 2.0, 4.0, 8.0, 8.0, 11.0),
}


def clb_timing(t):
    """Distribute the table values over the model (ps). T_ILO applies from the PIP at the CLB input to the output
    in the channel, so it includes the input mux and the output driver; T_QLO (Q via F/G to the output) is the
    delay of the function itself. Hence: LUT = T_QLO, output driver = T_ILO - T_QLO, clock-to-Q = T_CKO - driver,
    setup at D = T_ICK - LUT (not negative), clock via C or G later than via K. Latched input of the IOB:
    clock to input T_LI, setup and hold at the pad T_PL, T_LP.
    Transparent latch: T_ITO = input via F and the latch to the output, so D -> Q = T_ITO - T_ILO.
    Set/reset: via F or G (T_RLO = LUT + S/R -> Q + driver) gives S/R -> Q = T_RLO - T_ILO; directly from A
    or D (T_RIO) the path is longer by T_RIO - T_RLO + T_QLO than without a LUT (pip class SRDIR)."""
    ilo, qlo, cko, ick, cco, cio = t[:6]
    out = ilo - qlo
    ps = lambda v: int(round(max(v, 0) * 1000))  # noqa: E731
    return dict(lut=ps(qlo), out=ps(out), ckq=ps(cko - out), setup=ps(ick - qlo), clk_c=ps(cco - cko),
                clk_g=ps(cio - qlo - cko), pid=ps(t[6]), op=ps(t[7]), tri=ps(max(t[8], t[9])), li=ps(t[10]),
                pl=ps(t[11]), lp=ps(t[12]), dq=ps(t[13] - ilo), sr=ps(t[15] - ilo), srdir=ps(t[14] - t[15] + qlo))


# Interconnect: the Data Book gives no numbers, only the model ("Interconnect Performance"): a chain of
# pass transistors is a chain of RC stages (resistance of each switch times the capacitance behind it),
# which starts anew at every driver. In nextpnr: switches (SM, PIP, input mux) unbuffered with resistance
# R_SW, the lines with their capacitance; CLB output and clock buffer are drivers. Estimated for -70: a
# single-length segment behind a switch about 0.5 ns, a Long Line 4 ns, the clock buffer 4 ns; the other
# speed grades in proportion to T_ILO.
R_SW, R_DRV = 2000000, 1000000  # milliohms: pass transistor, output driver of the CLB
C_SEG, C_LONG = 250, 2000  # femtofarads: single-length segment, Long Line
T_GCLK = 4000  # ps: clock buffer


def set_timings(ch: Chip):
    tmg = ch.set_speed_grades(sorted(DATABOOK, key=int))
    for speed, table in DATABOOK.items():
        s = table[0] / DATABOOK["70"][0]  # interconnect in proportion to T_ILO
        c = clb_timing(table)
        tv = lambda v: TimingValue(int(round(v)))  # noqa: E731
        for name, delay, res, cap, buffered in (
                ("SM", 300 * s, R_SW * s, C_SEG, False), ("PIP", 200 * s, R_SW * s, C_SEG, False),
                ("INMUX", 0, R_SW * s, 0, False), ("GCLK", T_GCLK * s, 0, 0, True),
                ("XYDRV", c["out"], R_DRV * s, 0, True), ("LOCAL", 0, 0, 0, True),
                ("CLKC", c["clk_c"], 0, 0, True), ("CLKG", c["clk_g"], 0, 0, True),
                ("SRDIR", c["srdir"], 0, 0, True)):
            tmg.set_pip_class(grade=speed, name=name, delay=tv(delay), in_cap=tv(cap), out_res=tv(res),
                              is_buffered=buffered)
        for name, cap in (("SEG", C_SEG), ("LONG", C_LONG), ("CLKNET", 0)):
            tmg.set_node_class(grade=speed, name=name, delay=TimingValue(0), res=TimingValue(0),
                               cap=TimingValue(cap))
        for cell, ins in (("XC2000_LUT3", ["I[%d]" % i for i in range(3)]),
                          ("XC2000_LUT4", ["I[%d]" % i for i in range(4)]),
                          ("XC2000_FGM", ["%s[%d]" % (h, i) for h in "FG" for i in range(3)] + ["S"])):
            lut = ch.timing.add_cell_variant(speed, cell)  # T_ILO does not depend on the function
            for i in ins:
                lut.add_comb_arc(i, "O", tv(c["lut"]))
        dff = ch.timing.add_cell_variant(speed, "XC2000_DFF")  # without pack() (loaded *.pnr.json)
        dff.add_setup_hold("CLK", "D", ClockEdge.RISING, tv(c["setup"]), TimingValue(0))
        dff.add_clock_out("CLK", "Q", ClockEdge.RISING, tv(c["ckq"]))
        # Variants of the storage element, pack() chooses one per cell (xc2064.cc, dff_timing): FF with rising or
        # falling edge (FFP, FFN), latch transparent at clock 1 or 0 (LP, LN: Q follows from the opening edge,
        # setup and hold at the closing one), plus D -> Q (latch, .D) and S, R -> Q (.SR) as combinational
        # arcs; pack() leaves out an arc where it would close a combinational loop
        rise, fall = ClockEdge.RISING, ClockEdge.FALLING
        for kind, open_edge, close_edge in (("FFP", rise, rise), ("FFN", fall, fall), ("LP", rise, fall),
                                            ("LN", fall, rise)):
            for d_arc in (False, True) if kind[0] == "L" else (False,):
                for sr_arc in (False, True):
                    v = ch.timing.add_cell_variant(speed, "XC2000_DFF.%s%s%s" % (kind, ".D" * d_arc, ".SR" * sr_arc))
                    v.add_setup_hold("CLK", "D", close_edge, tv(c["setup"]), TimingValue(0))
                    v.add_clock_out("CLK", "Q", open_edge, tv(c["ckq"]))
                    if d_arc:
                        v.add_comb_arc("D", "Q", tv(c["dq"]))
                    if sr_arc:
                        v.add_comb_arc("S", "Q", tv(c["sr"]))
                        v.add_comb_arc("R", "Q", tv(c["sr"]))
        inff = ch.timing.add_cell_variant(speed, "XC2000_INFF")  # latched input of the IOB
        inff.add_setup_hold("K", "PAD", ClockEdge.RISING, tv(c["pl"]), tv(c["lp"]))
        inff.add_clock_out("K", "O", ClockEdge.RISING, tv(c["li"]))
        # IOB: pad -> input T_PID, output -> pad T_OP, T -> pad the larger of T_THZ and T_TON
        for cell, arcs in (("XC2000_INBUF", (("PAD", "O", "pid"),)),
                           ("XC2000_OUTBUF", (("I", "PAD", "op"),)),
                           ("XC2000_TOBUF", (("I", "PAD", "op"), ("T", "PAD", "tri"))),
                           ("XC2000_IOBUF", (("I", "PAD", "op"), ("T", "PAD", "tri"), ("PAD", "O", "pid")))):
            v = ch.timing.add_cell_variant(speed, cell)
            for a, b, k in arcs:
                v.add_comb_arc(a, b, tv(c[k]))


def set_packages(ch: Chip):
    """Packages PC68, PD48, PC44 and PG68 (xc2064db.packages): pin name in the package -> IOB Bel"""
    by_pin = {p["pin"]: p for p in PAD_INFO}
    for package in packages.PACKAGES:
        pkg = ch.create_package(package)
        for pin, pad in packages.pads(package, list(by_pin)).items():
            p = by_pin[pad]
            pkg.create_pad(pin, "X%dY%d" % (p["x"], p["y"]), pad, "IO", 0)


def main():
    ch = Chip("xc2064", "XC2064", X, Y)
    ch.strs.read_constids(path.join(path.dirname(__file__), "constids.inc"))
    ch.read_gfxids(path.join(path.dirname(__file__), "gfxids.inc"))
    Builder(ch).build()
    set_timings(ch)
    set_packages(ch)
    ch.write_bba(sys.argv[1])


if __name__ == "__main__":
    main()
