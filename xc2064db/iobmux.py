# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""IOBs: sources of the output mux (O, "Pnn.O" in XACT) and of the tristate mux (T) with their codes, and the
pips of the input (I) onto the lines, reproduced from Shirriff's iob.js (generateIobPips).

An entry in iob.js is the crossing of a stub of the IOB with a line: "|col.?.x:row.A.local.2"
(vertical stub col.?.x of the IOB, routing line row.A.local.2) or "-col.?.long.1:row.A.io3"
(horizontal stub, routing line col.?.long.1); "?" is the column or row of the tile.
Entries without | or - are direct connections (X/Y of a CLB, clock lines, pad -> CLB pin).

The stubs at the edge (io1-io6, x, clbl, clbr, clbw, local.0, local.5 of the edge rows and columns) are
parts of the IOB, not routing lines. The O and T muxes are encoded (bits "IOB Pnn.O/T MuxBit"); the code
of the T bits also selects the mode: tristate with a source, off (output never active) or on (always active).

Clock of the latched inputs (Data Book: the IOBs of one chip side share one clock): one clock line per side,
to which every IOB of that side is hardwired (iob.js: kin), driven by a K mux at a corner with sources from the
edge channel of the same side. The bit map assigns the 4 bits of each K mux to a pad ("IOB P9.K MuxBit", P9
top, P59 right, P27 bottom, P24 left), codes from iob.js (generateIobPips).

Inputs of the clock buffers (datasheet Figure 8b): GCLK at the top left (bits "CLB CLK.AA.I MuxBit 0-5") and
ACLK at the bottom right ("CLB CLK.II.I MuxBit 0-7"). Shirriff does not decode them, and no XACT bitstream uses
them. Sources and codes come from MAKEBITS (XACT 5.2.0, only as a black box): per source an LCA with exactly
this pip (Program {xGy}), and from it the bitstream. Bit 5 switches in one of five sources on bits 0-4 (active
0, like the other muxes); with no bit programmed, the first source of the table applies. ACLK can also be
driven by the crystal oscillator at P43/P46 (XACT OSC.II.O, bits 6 and 7).
"""
import collections
import re

from . import sources

Entry = collections.namedtuple("Entry", "index spec kind line col row g special")
# kind: route (routing line in line), x/y (X or Y of the CLB in special), gclk, aclk_in (P43 -> ACLK buffer),
#       clb (pad -> CLB pin in special), stub (IOB stub in special, signal unknown),
#       pad (input of the pad in special into a clock buffer), osc (crystal oscillator)
# special cases "@x:AH=col.H.clbr3:row.?.io3": after "=" the crossing from iob.js (G position for XACT's Program)

# K muxes: pad of the bits -> (side, stub of the mux at the corner, sources in the order of iob.js,
# code -> index). "@gclk" is CLK.AA.O or col.A.clk (GCLK), "@stub:..." an IOB stub of unknown
# origin.
KMUX_SPEC = {
    "P9": ("T", "col.I.local.0", ["@gclk", "row.A.local.1", "row.A.local.2", "row.A.local.3", "row.A.local.4",
                                  "row.A.long.3"], {4: 0, 8: 1, 15: 2, 14: 3, 9: 4, 5: 5}),
    "P59": ("R", "row.A.local.5", ["@stub:col.I.io3", "col.I.long.2", "col.I.local.1", "col.I.local.2",
                                   "col.I.local.3", "col.I.local.4"], {4: 0, 8: 1, 15: 4, 14: 3, 9: 2, 5: 5}),
    "P27": ("B", "col.A.local.5", ["@stub:row.I.io4", "row.I.long.1", "row.I.local.1", "row.I.local.2",
                                   "row.I.local.3", "row.I.local.4"], {4: 2, 8: 4, 15: 5, 14: 0, 2: 1, 3: 3}),
    "P24": ("L", "row.I.local.0", ["col.A.local.1", "col.A.local.2", "col.A.local.3", "col.A.local.4",
                                   "col.A.long.3", "@gclk"], {4: 1, 2: 5, 15: 4, 14: 3, 9: 0, 5: 2}),
}
SIDES = "TRBL"
KMux = collections.namedtuple("KMux", "pin side stub sources codes bits")

# Input muxes of the clock buffers: mux -> (clock net, [(code, source, crossing G)]), the default setting first.
# Source: line, "@pad:Pnn" (input of the pad, PADn.I in XACT) or "@osc"
CLKMUX_SPEC = {
    "CLK.AA.I": ("GCLK", [(63, "row.A.local.3", "16G164"), (30, "@pad:P11", "16G149"), (29, "@pad:P9", "16G156"),
                          (27, "col.A.local.3", "8G157"), (23, "col.A.long.3", "11G157"),
                          (15, "row.A.long.3", "16G161")]),
    "CLK.II.I": ("ACLK", [(255, "row.I.local.2", "165G9"), (222, "@pad:P46", "168G13"),
                          (221, "col.I.long.2", "170G13"), (219, "col.I.local.2", "173G13"),
                          (215, "@pad:P43", "165G14"), (207, "row.I.long.1", "165G12"), (63, "@osc", "167G5")]),
}
ClkMux = collections.namedtuple("ClkMux", "name net sources codes bits")


class Iob:
    def __init__(self, pin, tile, style, pad):
        self.pin, self.tile, self.style, self.pad = pin, tile, style, pad
        self.o, self.i, self.t = [], [], []  # lists of Entry
        self.omux = {}  # code -> index in o
        self.tmux = {}  # code -> index in t (tristate)
        self.t_off = self.t_on = None  # codes: output off or always on
        self.obits, self.tbits = {}, {}  # n -> bit number


def pads():
    """Pad table from iob.js: [(pin, tile, style, PADn)]"""
    js = sources.read_text(sources.IOB_JS)
    return re.findall(r'\["(P\d+)",\s*"([A-I][A-I])",\s*"(\w+)",\s*"(PAD\d+)"\]', js)


def _lists(pin, tile, d):
    """o, i, t, omux, (tmux, t_off, t_on) as in generateIobPips"""
    r, c = tile
    prev_r, prev_c = chr(ord(r) - 1), chr(ord(c) - 1)
    std_t_top = {3: 0, 1: 1, 7: 2, 5: 3}
    if d == "topleft":
        t = ["|col.?.clbl1:row.A.long.2", "|col.?.clbl1:row.A.local.1", "|col.?.clbl1:row.A.local.3",
             "|col.?.clbl1:row.A.long.3"]
        tm = (std_t_top, 4, 6)
        if tile == "AA":
            o = ["@gclk=col.?.io3:CLK.AA.O", "|col.?.io3:row.A.long.2", "|col.?.io3:row.A.local.2",
                 "|col.?.io3:row.A.local.4",
                 "-col.A.long.3:row.?.local.5", "-col.A.local.3:row.?.local.5", "-col.A.local.1:row.?.local.5",
                 "-col.A.long.2:row.?.local.5"]
            i = ["|col.?.x:row.A.local.1", "|col.?.x:row.A.local.3", "|col.?.x:row.A.long.3",
                 "-col.A.io2:row.?.io5", "-col.A.long.4:row.?.io5", "-col.A.local.4:row.?.io5",
                 "-col.A.local.2:row.?.io5", "-col.A.long.2:row.?.io5", "@clb:AA.A", "@clb:AA.B"]
            om = {12: 0, 20: 1, 25: 2, 30: 3, 24: 4, 21: 5, 31: 6, 13: 7}
        else:
            o = ["|col.?.x:row.A.long.2", "|col.?.x:row.A.local.2", "|col.?.x:row.A.local.4",
                 "-col.?.long.1:row.A.io3", "-col.?.local.3:row.A.io3", "-col.?.local.1:row.A.io3"]
            i = ["|col.?.clbl2:row.A.local.1", "|col.?.clbl2:row.A.local.3", "|col.?.clbl2:row.A.long.3",
                 "-col.?.long.2:row.A.io4", "-col.?.local.5:row.A.io4", "-col.?.local.4:row.A.io4",
                 "-col.?.local.2:row.A.io4", "@clb:A%s.A" % c, "@clb:A%s.B" % c]
            om = {4: 0, 9: 1, 14: 2, 8: 3, 5: 4, 15: 5}
    elif d == "topright":
        t = ["|col.?.clbw3:row.A.long.2", "|col.?.clbw3:row.A.local.1", "|col.?.clbw3:row.A.local.3",
             "|col.?.clbw3:row.A.long.3"]
        tm = (std_t_top, 6, 4)
        om = {13: 0, 10: 1, 11: 2, 12: 3, 30: 4, 6: 5, 7: 6, 31: 7}
        if tile == "AI":
            o = ["|col.?.clbw1:row.A.local.1", "|col.?.clbw1:row.A.local.3", "|col.?.clbw1:row.A.long.3",
                 "@x:AH=col.H.clbr3:row.?.io3", "-col.I.long.1:row.?.io3", "-col.I.local.1:row.?.io3",
                 "-col.I.local.3:row.?.io3", "-col.I.long.3:row.?.io3"]
            i = ["|col.?.clbw2:row.A.long.2", "|col.?.clbw2:row.A.local.2", "|col.?.clbw2:row.A.local.4",
                 "-col.I.long.2:row.?.io2", "-col.I.local.2:row.?.io2", "-col.I.local.4:row.?.io2",
                 "-col.I.long.3:row.?.io2"]
        else:
            o = ["|col.?.clbw1:row.A.local.1", "|col.?.clbw1:row.A.local.3", "|col.?.clbw1:row.A.long.3",
                 "@x:A%s=col.?.clbw3:row.A.io2" % prev_c, "-col.?.local.2:row.A.io2", "-col.?.local.4:row.A.io2",
                 "-col.?.local.5:row.A.io2", "-col.?.long.2:row.A.io2"]
            i = ["|col.?.clbw2:row.A.long.2", "|col.?.clbw2:row.A.local.2", "|col.?.clbw2:row.A.local.4",
                 "-col.?.local.1:row.A.local.5", "-col.?.local.3:row.A.local.5", "-col.?.long.1:row.A.local.5"]
    elif d == "rightlower":
        t = ["-col.I.long.3:row.?.io1", "-col.I.local.4:row.?.io1", "-col.I.local.2:row.?.io1",
             "-col.I.long.2:row.?.io1"]
        tm = ({3: 0, 5: 1, 1: 2, 7: 3}, 6, 4)
        i = ["-col.I.long.3:row.?.io2", "-col.I.local.3:row.?.io2", "-col.I.local.1:row.?.io2",
             "-col.I.long.1:row.?.io2", "|col.I.io1:row.?.local.3", "|col.I.io1:row.?.local.5"]
        o = ["-col.I.local.4:row.?.io3", "-col.I.local.2:row.?.io3", "-col.I.long.2:row.?.io3",
             "|col.I.io2:row.?.local.1", "|col.I.io2:row.?.local.4", "|col.I.io2:row.?.long.1",
             "@x:%sH=col.I.io2:%sH.B" % (prev_r, prev_r), "@y:%sH=col.I.io2:%sH.Y" % (prev_r, prev_r)]
        om = {6: 0, 30: 1, 20: 2, 21: 3, 19: 4, 18: 5, 7: 6, 31: 7}
    elif d == "rightupper":
        t = ["-col.I.long.3:row.?.io4", "-col.I.local.4:row.?.io4", "-col.I.local.2:row.?.io4",
             "-col.I.long.2:row.?.io4"]
        tm = ({5: 0, 3: 1, 7: 2, 1: 3}, 6, 4)
        i = ["-col.I.local.4:row.?.io5", "-col.I.local.2:row.?.io5", "-col.I.long.2:row.?.io5",
             "|col.I.io3:row.?.long.1", "|col.I.io3:row.?.local.4", "|col.I.io3:row.?.local.1"]
        o = ["-col.I.long.3:row.?.io6", "-col.I.local.3:row.?.io6", "-col.I.local.1:row.?.io6",
             "-col.I.long.1:row.?.io6", "|col.I.local.0:row.?.local.5", "|col.I.local.0:row.?.local.3",
             "@x:%sH=col.I.local.0:%sH.B" % (r, r), "@y:%sH=col.I.local.0:%sH.Y" % (r, r)]
        om = {31: 0, 25: 1, 21: 2, 13: 3, 12: 4, 24: 5, 20: 6, 30: 7}
    elif d == "bottomright":
        t = ["|col.?.clbw3:row.I.long.2", "|col.?.clbw3:row.I.local.4", "|col.?.clbw3:row.I.local.2",
             "|col.?.clbw3:row.I.long.1"]
        tm = (std_t_top, 6, 4)
        if tile == "II":
            o = ["|col.?.clbw1:row.I.clk", "|col.?.clbw1:row.I.local.4", "|col.?.clbw1:row.I.local.2",
                 "|col.?.clbw1:row.I.long.1", "-col.?.long.2:row.I.io2", "-col.?.local.2:row.I.io2",
                 "-col.?.local.4:row.I.io2", "-col.?.long.3:row.I.io2", "@x:HH=col.?.clbw3:row.I.io2"]
            i = ["|col.?.clbw2:row.I.long.2", "|col.?.clbw2:row.I.local.3", "|col.?.clbw2:row.I.local.1",
                 "@aclk_in", "-col.?.long.1:row.I.io3", "-col.?.local.1:row.I.io3", "-col.?.local.3:row.I.io3",
                 "-col.?.long.3:row.I.io3"]
            om = {14: 0, 45: 1, 42: 2, 43: 3, 39: 4, 62: 5, 38: 6, 63: 7, 44: 8}
        else:
            o = ["|col.?.clbw1:row.I.local.4", "|col.?.clbw1:row.I.local.2", "|col.?.clbw1:row.I.long.1",
                 "-col.?.local.2:row.I.io3", "-col.?.local.4:row.I.io3", "-col.?.local.5:row.I.io3",
                 "-col.?.long.2:row.I.io3", "@x:H%s=col.?.clbw3:row.I.io3" % prev_c]
            i = ["|col.?.clbw2:row.I.long.2", "|col.?.clbw2:row.I.local.3", "|col.?.clbw2:row.I.local.1",
                 "-col.?.local.1:row.I.io4", "-col.?.local.3:row.I.io4", "-col.?.long.1:row.I.io4"]
            om = {13: 0, 10: 1, 11: 2, 30: 3, 6: 4, 7: 5, 31: 6, 12: 7}
    elif d == "bottomleft":
        t = ["|col.?.clbl1:row.I.long.2", "|col.?.clbl1:row.I.local.4", "|col.?.clbl1:row.I.local.2",
             "|col.?.clbl1:row.I.long.1"]
        tm = (std_t_top, 4, 6)
        if tile == "IA":
            o = ["|col.?.io3:row.I.long.2", "|col.?.io3:row.I.local.3", "|col.?.io3:row.I.local.1",
                 "-col.A.long.3:row.?.io2", "-col.A.local.3:row.?.io2", "-col.A.local.1:row.?.io2",
                 "-col.A.long.2:row.?.io2"]
            i = ["|col.?.x:row.I.local.4", "|col.?.x:row.I.local.2", "|col.?.x:row.I.long.1",
                 "-col.A.long.4:row.?.io1", "-col.A.local.4:row.?.io1", "-col.A.local.2:row.?.io1",
                 "-col.A.long.2:row.?.io1", "@clb:HA.D", "@clb:HA.C"]
            om = {20: 0, 25: 1, 30: 2, 24: 3, 21: 4, 31: 5, 12: 6}
        else:
            o = ["|col.?.x:row.I.long.2", "|col.?.x:row.I.local.3", "|col.?.x:row.I.local.1",
                 "-col.?.long.1:row.I.io2", "-col.?.local.3:row.I.io2", "-col.?.local.1:row.I.io2"]
            i = ["|col.?.clbl2:row.I.local.4", "|col.?.clbl2:row.I.local.2", "|col.?.clbl2:row.I.long.1",
                 "-col.?.long.2:row.I.io1", "-col.?.local.5:row.I.io1", "-col.?.local.4:row.I.io1",
                 "-col.?.local.2:row.I.io1", "@clb:H%s.D" % c, "@clb:H%s.C" % c]
            om = {4: 0, 9: 1, 14: 2, 8: 3, 5: 4, 15: 5}
    elif d == "leftupper":
        t = ["-col.A.long.2:row.?.io4", "-col.A.local.1:row.?.io4", "-col.A.local.3:row.?.io4",
             "-col.A.long.3:row.?.io4"]
        tm = ({6: 0, 0: 1, 4: 2, 2: 3}, 5, 7)
        i = ["-col.A.long.2:row.?.io5", "-col.A.local.1:row.?.io5", "-col.A.local.3:row.?.io5",
             "-col.A.long.3:row.?.io5", "|col.A.local.5:row.?.local.5"]
        if tile == "HA":
            i.append("@clb:HA.B")
        o = ["-col.A.local.2:row.?.io6", "-col.A.local.4:row.?.io6", "-col.A.long.4:row.?.io6",
             "|col.A.io1:row.?.long.1", "|col.A.io1:row.?.local.4", "|col.A.io1:row.?.local.1"]
        om = {4: 0, 8: 1, 14: 2, 5: 3, 9: 4, 15: 5}
    elif d == "leftlower":
        t = ["-col.A.long.2:row.?.io1", "-col.A.local.1:row.?.io1", "-col.A.local.3:row.?.io1",
             "-col.A.long.3:row.?.io1"]
        tm = ({6: 0, 0: 1, 4: 2, 2: 3}, 5, 7)
        i = ["-col.A.local.2:row.?.io2", "-col.A.local.4:row.?.io2", "-col.A.long.4:row.?.io2",
             "-col.A.io2:row.?.io2", "|col.A.io3:row.?.local.4", "|col.A.io3:row.?.long.1",
             "@clb:%sA.B" % prev_r]
        o = ["-col.A.long.2:row.?.io3", "-col.A.local.1:row.?.io3", "-col.A.local.3:row.?.io3",
             "-col.A.long.3:row.?.io3", "|col.A.io2:row.?.local.3", "|col.A.io2:row.?.local.5"]
        om = {5: 0, 3: 1, 15: 2, 4: 3, 2: 4, 14: 5}
    else:
        raise ValueError("unknown IOB kind %s" % d)
    return o, i, t, om, tm


def _entry(idx, spec, tile, lines):
    """One entry from iob.js -> Entry (routing line or special case, the latter with G position if known)"""
    if spec.startswith("@"):
        head, _, cross = spec[1:].partition("=")
        kind, _, arg = head.partition(":")
        g = None
        if cross:
            a, b = cross.split(":")
            g = "%dG%d" % (lines.col_info[a.replace("?", tile[1], 1)][0], lines.row_info[b.replace("?", tile[0], 1)][0])
        return Entry(idx, spec, kind, None, None, None, g, arg or None)
    d, a, b = spec[0], *spec[1:].split(":")
    col = a.replace("?", tile[1], 1)
    row = b.replace("?", tile[0], 1)
    g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
    col, row = lines.canonical_col(col), lines.canonical_row(row)
    line = row if d == "|" else col
    return Entry(idx, spec, "route", line, col, row, g, None)


def iobs(lines, entries):
    """Pin -> Iob for all 58 pads, with bits from the bit map"""
    result = {}
    for pin, tile, style, pad in pads():
        iob = Iob(pin, tile, style, pad)
        o, i, t, om, (tmux, t_off, t_on) = _lists(pin, tile, style)
        iob.o = [_entry(k, s, tile, lines) for k, s in enumerate(o)]
        iob.i = [_entry(k, s, tile, lines) for k, s in enumerate(i)]
        iob.t = [_entry(k, s, tile, lines) for k, s in enumerate(t)]
        iob.omux, iob.tmux, iob.t_off, iob.t_on = om, tmux, t_off, t_on
        result[pin] = iob
    for e in entries:
        if e.kind == "iobmux" and e.key[0] in result:
            pin, which, n = e.key
            if which == "O":
                result[pin].obits[n] = e.index
            elif which == "T":
                result[pin].tbits[n] = e.index
    for iob in result.values():
        for name, bits, codes in (("O", iob.obits, iob.omux), ("T", iob.tbits, iob.tmux)):
            if sorted(bits) != list(range(len(bits))):
                raise ValueError("%s.%s: mux bits %s not contiguous" % (iob.pin, name, sorted(bits)))
            bad = [c for c in codes if c >= 1 << len(bits)]
            if bad:
                raise ValueError("%s.%s: codes %s do not fit into %d bits" % (iob.pin, name, bad, len(bits)))
    return result


def kmuxes(lines, entries):
    """Pad of the bits -> KMux (sources as Entry at the crossing with the stub, bits: n -> bit number)"""
    bits = collections.defaultdict(dict)
    for e in entries:
        if e.kind == "iobmux" and e.key[1] == "K":
            bits[e.key[0]][e.key[2]] = e.index
    result = {}
    for pin, (side, stub, specs, codes) in KMUX_SPEC.items():
        sources = []
        for k, spec in enumerate(specs):
            if spec.startswith("@"):
                kind, _, arg = spec[1:].partition(":")
                g = None
                if kind == "gclk":  # crossing of the stub with CLK.AA.O (top) or col.A.clk (left)
                    col, row = (stub, "CLK.AA.O") if stub.startswith("col.") else ("col.A.clk", stub)
                    g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
                sources.append(Entry(k, spec, kind, None, None, None, g, arg or None))
                continue
            col, row = (stub, spec) if stub.startswith("col.") else (spec, stub)
            g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
            col, row = lines.canonical_col(col), lines.canonical_row(row)
            sources.append(Entry(k, spec, "route", row if stub.startswith("col.") else col, col, row, g, None))
        if sorted(bits[pin]) != [0, 1, 2, 3] or any(c >= 16 for c in codes):
            raise ValueError("%s.K: mux bits %s or codes do not match" % (pin, sorted(bits[pin])))
        result[pin] = KMux(pin, side, stub, sources, codes, bits[pin])
    return result


def clkmuxes(lines, entries):
    """Mux (CLK.AA.I, CLK.II.I) -> ClkMux (sources as Entry at their crossing, codes: code -> index,
    bits: n -> bit number)"""
    bits = collections.defaultdict(dict)
    for e in entries:
        if e.kind == "clkmux":
            bits[e.key[0]][e.key[1]] = e.index
    result = {}
    for name, (net, specs) in CLKMUX_SPEC.items():
        sources, codes = [], {}
        for k, (c, spec, g) in enumerate(specs):
            codes[c] = k
            if spec.startswith("@"):
                kind, _, arg = spec[1:].partition(":")
                sources.append(Entry(k, spec, kind, None, None, None, g, arg or None))
                continue
            gx, gy = (int(v) for v in g.split("G"))
            col, row = lines.col_name[gx], lines.row_name[gy]
            if spec not in (col, row):
                raise ValueError("%s: source %s does not lie at the crossing %s (%s, %s)" % (name, spec, g, col, row))
            sources.append(Entry(k, spec, "route", spec, col, row, g, None))
        n = len(bits[name])
        if sorted(bits[name]) != list(range(n)) or any(c >= 1 << n for c in codes):
            raise ValueError("%s: mux bits %s or codes do not match" % (name, sorted(bits[name])))
        if (1 << n) - 1 not in codes:
            raise ValueError("%s: no source for the default setting" % name)
        result[name] = ClkMux(name, net, sources, codes, bits[name])
    return result


def code(bits, raw):
    return sum(raw[b] << n for n, b in bits.items())


def source_name(ent):
    """Name of a source of the O, T, K or clock buffer mux in the text format: line, X/Y of a CLB, GCLK,
    stub, pad (P9) or OSC"""
    if ent.kind == "route":
        return ent.line
    if ent.kind in ("x", "y"):
        return "%s.%s" % (ent.special, ent.kind.upper())
    if ent.kind in ("stub", "pad"):
        return ent.special
    return ent.kind.upper()
