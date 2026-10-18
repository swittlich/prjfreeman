# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""Routing graph of the XC2064 built from the data (as of stage 3: the CLB array with its channels, and the IOBs).

Nodes are electrically connected pieces of line; connections are the programmable points of the bit map (PIP
bits, magic bits of the switch matrices, codes of the CLB and IOB muxes) and fixed wiring.

Segments (datasheet "General-Purpose Interconnect", Figure 7b; positions from the G coordinates):
  - The vertical single-length segments local.1-4 and the horizontal ones of the switch matrices end at the
    matrices. A pin lies at gPt + (DX, DY) (switches); the matrix separates the vertical lines of its top and
    bottom pins between their heights, the horizontal ones between the left and right pins.
    Nodes: "col.C.local.k@R" (column C, piece below the matrix in row R) and "row.R.local.k@C".
  - The fifth vertical line (local.5) has no matrix. Its piece for row R starts at the junction point
    "col.C.local.5:row.R.local.0", runs in channel R on the track of local.6 (crossings with local.3/4), then on
    the track of local.5 past CLB row R (B, C, Y) into channel R+1 (crossings with its local.0, local.3,
    local.4). The junction point of row R connects piece R-1 to piece R. In row A there is no piece above it;
    the crossings in row I belong to piece H. Node "col.C.local.5@R". Confirmed by TEST1.LCA (net p1).
  - Long Lines run over the full height or width: node = line name.
  - GCLK (col.*.clk, CLK.AA.O) is one node "GCLK", the ACLK line at the bottom (row.I.clk) one node "ACLK",
    driven by the clock buffers; their input muxes are connections clkbuf (iobmux.clkmuxes).
  - CLB outputs: X (row io6) and Y (row y) of a CLB are "RC.X", "RC.Y", inputs "RC.A" ... "RC.K".
  - Direct connections (datasheet "Direct Interconnect"): X is hardwired to A/B of the CLB below (sources
    row.R.io4, col.C.x at b) and C/D of the CLB above (col.C.x at c, row.R+1.io3), Y to B of the CLB to the
    right (col.C.local.6 at b). At the edge these sources are pads: the input "Pnn.I" of the pad (iob.js).
  - IOBs (iob.js): nodes "Pnn.O" (output mux to the pad), "Pnn.T" (tristate mux) and "Pnn.I" (input from the
    pad). The pin lines at the crossings (io1-io6, x, clbl/clbr/clbw, local.0 and local.5 at the edge)
    belong to the IOB and are not nodes of their own.
  - Clock of the latched IOB inputs: one node "IOCLK.T/R/B/L" per chip side (top row.A.local.0, right
    col.I.local.5, bottom row.I.local.5, left col.A.local.0), driven by the K mux of that side; the clock input
    "Pnn.K" of each IOB is hardwired to the line of its side.

Connection kinds (Conn.kind): pip (PIP bit, between general lines in both directions), out (PIP bit from X/Y
onto a line), clkout (PIP bit from ACLK onto a vertical Long Line, in this direction only: ACLK is always driven
by its buffer, even in the default setting), switch (magic bit), junction (junction point of the fifth line),
mux (CLB input: source -> pin, bits = mux bits, code), iobo/iobt (output or T mux of an IOB: source ->
Pnn.O/T, with code; driver off/on are codes without a source), iobi (PIP bit: Pnn.I -> line), iobk (K mux:
source -> IOCLK.<side>, with code), iobkin (fixed: IOCLK.<side> -> Pnn.K, without a bit), clkbuf (input of a
clock buffer: line or Pnn.I -> GCLK/ACLK, with code), bidi (repowering buffer, only in the check mode
split_bidi). The entries from iob.js without a PIP bit are in Graph.unmodelled. Constants do not exist as a
line in the original (nextpnr: pack() folds them into LUT contents).
"""
import bisect
import collections
import re

from . import bitmap, clbmux, iobmux, switches
from .lines import Lines

LETTERS = "ABCDEFGHI"
Conn = collections.namedtuple("Conn", "kind a b bits code name")
Buffer = collections.namedtuple("Buffer", "name line g bit seg")
CODED = ("mux", "iobo", "iobt", "iobk", "clkbuf", "bidi")  # connections via a code instead of a PIP bit


def conn_on(cn, raw):
    """Is the connection switched on in the bitstream raw (0 = programmed)? Code None (unknown): never."""
    if cn.kind in CODED:
        return cn.code is not None and sum(raw[b] << n for n, b in enumerate(cn.bits)) == cn.code
    return all(raw[b] == 0 for b in cn.bits)


def _split(name):
    m = re.fullmatch(r"(col|row)\.([A-I])\.(.+)", name)
    return (m[1], m[2], m[3]) if m else (None, None, name)


def _prev(c):
    return chr(ord(c) - 1)


def _next(c):
    return chr(ord(c) + 1)


class Graph:
    def __init__(self, entries=None, lines=None, split_bidi=False):
        """split_bidi: split the single-length segments at the repowering buffers (piece beyond: suffix "+",
        buffer as two directed connections "bidi" with the bit value as code). For checks only: a buffer is
        never off, so both pieces always carry the same net; for the router the segment stays one node, the
        direction follows from the routing (bidi_bit)."""
        self.entries = entries or bitmap.load()
        self.lines = lines or Lines()
        self.split_bidi = split_bidi
        self.conns = []
        self.unmodelled = []  # (pin, entry from iob.js, reason)
        self._cuts()
        self._bidi()
        self._pips()
        self._switches()
        self._iobs()
        self._iob_clocks()
        self._muxes()
        self._clkbufs()
        used = {b for cn in self.conns for b in cn.bits}
        self.skipped = collections.Counter(
            "PIP %s" % self.lines.pip_name(e.key[0]) for e in self.entries if e.kind == "pip" and e.index not in used)

    # --- Segments ------------------------------------------------------------------------------
    def _cuts(self):
        """Cut points per line: list of (center, letter of the matrix) along the line"""
        ln = self.lines
        self.sm_g = switches.positions(ln)
        col_cuts, row_cuts = collections.defaultdict(list), collections.defaultdict(list)
        self.sm_pins = {}  # (matrix, pin) -> (line, side)
        for sm, g in self.sm_g.items():
            gx, gy = (int(v) for v in g.split("G"))
            t = sm[:2]
            for pin in range(1, 9):
                px, py = switches.pin_g(g, pin)
                side = switches.SIDE[pin]
                line = ln.col_name.get(px) if side in ("top", "bottom") else ln.row_name.get(py)
                self.sm_pins[(sm, pin)] = (line, side)
            for pin in (1, 2):
                line = self.sm_pins[(sm, pin)][0]
                if line:
                    col_cuts[line].append((gy - 1.5, t[0]))
            for pin in (3, 4):
                line = self.sm_pins[(sm, pin)][0]
                if line:
                    row_cuts[line].append((gx + 0.5, t[1]))
        # vertical: from the top (large G) downwards; horizontal: from left to right
        self.col_cuts = {k: sorted(v, key=lambda c: -c[0]) for k, v in col_cuts.items()}
        self.row_cuts = {k: sorted(v) for k, v in row_cuts.items()}

    def _bidi(self):
        """Repowering buffers at the boundaries of the 9 sections (datasheet): one buffer per bidi bit on a
        single-length segment, vertical above rows D and G (all local.1-5), horizontal before columns D and G.
        Bit 0 (programmed): the buffer drives down or right, bit 1: up or left (confirmed with TEST1.RBT and
        AND_OR.BIT, see bidi_check). buffers: list of Buffer(name, line, position G along the line, bit,
        segment)."""
        self.buffers = []
        self.bidi_at = collections.defaultdict(list)
        for e in self.entries:
            if e.kind != "bidi":
                continue
            gx, gy = (int(v) for v in e.key[0].split("G"))
            col, row = self.lines.col_name.get(gx), self.lines.row_name.get(gy)
            if (col is None) == (row is None):
                raise ValueError("Bidi %s does not lie on exactly one line" % e.key[0])
            line, g = (col, gy) if col else (row, gx)
            seg = self._seg_base(line, g, line.startswith("col."))
            self.buffers.append(Buffer(e.key[0], line, g, e.index, seg))
            self.bidi_at[line].append((g, e.index, e.key[0]))
        if self.split_bidi:
            for b in self.buffers:
                self.conns.append(Conn("bidi", b.seg, b.seg + "+", [b.bit], 0, "%s %s" % (b.name, b.line)))
                self.conns.append(Conn("bidi", b.seg + "+", b.seg, [b.bit], 1, "%s %s" % (b.name, b.line)))

    def bidi_bit(self, buf, g_in):
        """Bit value of the buffer buf when the signal enters its segment at g_in (G along the line)"""
        before = g_in > buf.g if buf.line.startswith("col.") else g_in < buf.g
        return 0 if before else 1

    def _beyond(self, line, base, g):
        """Node at position g of the piece base: base itself or, in the check mode split_bidi beyond a buffer
        of the piece (below it or to its right), base + "+" """
        if not self.split_bidi:
            return base
        vertical = line.startswith("col.")
        for bg, _, _ in self.bidi_at.get(line, ()):
            if (g < bg if vertical else g > bg) and self._seg_base(line, bg, vertical) == base:
                return base + "+"
        return base

    def _seg_base(self, line, g, vertical):
        return self._seg_col(line, g) if vertical else self._seg_row(line, g)

    def seg_col(self, line, y):
        """Node of the vertical line line at height y (G)"""
        return self._beyond(line, self._seg_col(line, y), y)

    def seg_row(self, line, x):
        """Node of the horizontal line line at position x (G)"""
        return self._beyond(line, self._seg_row(line, x), x)

    def _seg_col(self, line, y):
        kind, c, rest = _split(line)
        if rest in ("local.5", "local.6") and c not in "AI":
            return self._fifth(c, y, rest)
        cuts = self.col_cuts.get(line)
        if not cuts:
            return line  # Long Line, clk
        ys = [-cy for cy, _ in cuts]
        i = bisect.bisect_left(ys, -y)
        for cy, _ in cuts:
            if abs(cy - y) < 1.5:
                raise ValueError("%s: crossing at G %d lies inside a switch matrix" % (line, y))
        r = cuts[i - 1][1] if i > 0 else _prev(cuts[0][1])
        if r < "A" or r > "H":
            raise ValueError("%s: crossing at G %d outside the segments" % (line, y))
        return "%s@%s" % (line, r)

    def _seg_row(self, line, x):
        cuts = self.row_cuts.get(line)
        if not cuts:
            return {"row.I.clk": "ACLK", "CLK.AA.O": "GCLK"}.get(line, line)
        xs = [cx for cx, _ in cuts]
        for cx, _ in cuts:
            if abs(cx - x) < 1.5:
                raise ValueError("%s: crossing at G %d lies inside a switch matrix" % (line, x))
        i = bisect.bisect_left(xs, x)
        c = cuts[i - 1][1] if i > 0 else _prev(cuts[0][1])
        if c < "A" or c > "H":
            raise ValueError("%s: crossing at G %d outside the segments" % (line, x))
        return "%s@%s" % (line, c)

    def row_of_y(self, y):
        """Row (A-I) whose block contains the height y (block R: from io1 of row R to y of row R)"""
        name = self.lines.row_name.get(y)
        _, r, _ = _split(name) if name else (None, None, None)
        if r:
            return r
        best = min(self.lines.row_name, key=lambda g: abs(g - y))
        return _split(self.lines.row_name[best])[1]

    def _fifth(self, c, y, which):
        r = self.row_of_y(y)
        if which == "local.6":
            return "col.%s.local.5@%s" % (c, r)
        if r == "A":
            return "col.%s.local.5@A" % c
        if r == "I":
            return "col.%s.local.5@H" % c
        jog = self.lines.row_info["row.%s.long.1" % r][0]
        return "col.%s.local.5@%s" % (c, _prev(r) if y > jog else r)

    # --- Connections ---------------------------------------------------------------------------
    @staticmethod
    def _general_col(c, kind):
        if re.fullmatch(r"local\.[1-4]|long\.\d", kind):
            return True
        return kind in ("local.5", "local.6") and c not in "AI"

    @staticmethod
    def _general_row(r, kind):
        if re.fullmatch(r"local\.[1-4]|long\.\d", kind):
            return True
        if kind == "local.5":
            return r not in "AI"
        if kind == "local.0":
            return r not in "AI"
        if kind == "clk":
            return r == "I"
        return kind in ("io6", "y") and r != "I"

    @staticmethod
    def _out_pip(c, ck, r, rk):
        """X of the CLBs in column H crosses the edge channel at the height of row b (col.I.* x row.R.b)"""
        return c == "I" and rk == "b" and r != "I" and re.fullmatch(r"local\.[1-4]|long\.\d", ck)

    def _pips(self):
        ln = self.lines
        for e in self.entries:
            if e.kind != "pip":
                continue
            g = e.key[0]
            gx, gy = (int(v) for v in g.split("G"))
            col, row = ln.col_name[gx], ln.row_name[gy]
            _, c, ck = _split(col)
            _, r, rk = _split(row)
            if not (self._general_col(c, ck) and self._general_row(r, rk)) and not self._out_pip(c, ck, r, rk):
                continue  # input pip of an IOB (_iobs) or not covered
            name = "%s:%s" % (col, row)
            if rk in ("io6", "y", "b"):  # CLB output X (column I: at height b) or Y of the CLB left of the column
                clb = r + _prev(c)
                src = "%s.%s" % (clb, "Y" if rk == "y" else "X")
                self.conns.append(Conn("out", src, self.seg_col(col, gy), [e.index], None, name))
            elif rk == "local.0":  # junction point of the fifth line (above D and G beyond the buffer)
                self.conns.append(Conn("junction", self.seg_col("col.%s.local.5" % c, gy),
                                       "col.%s.local.5@%s" % (c, r), [e.index], None, name))
            elif rk == "clk":  # ACLK is the output of its buffer (XACT: col.D.long.2:CLK.II.O)
                self.conns.append(Conn("clkout", "ACLK", self.seg_col(col, gy), [e.index], None, name))
            else:
                self.conns.append(Conn("pip", self.seg_col(col, gy), self.seg_row(row, gx), [e.index], None, name))

    def _switches(self):
        conn = switches.connections(self.entries, self.lines)
        for sm, pairs in sorted(conn.items()):
            for (p1, p2), bit in sorted(pairs.items()):
                a, b = self.sm_node(sm, p1), self.sm_node(sm, p2)
                self.conns.append(Conn("switch", a, b, [bit], None, "%s %d-%d" % (sm, p1, p2)))

    def sm_node(self, sm, pin):
        """Node at a pin of a switch matrix"""
        line, side = self.sm_pins[(sm, pin)]
        t = sm[:2]
        px, py = switches.pin_g(self.sm_g[sm], pin)
        if side == "top":
            return self._beyond(line, "%s@%s" % (line, _prev(t[0])), py)
        if side == "bottom":
            return "%s@%s" % (line, t[0])
        if side == "left":
            return self._beyond(line, "%s@%s" % (line, _prev(t[1])), px)
        return "%s@%s" % (line, t[1])

    def _iobs(self):
        """IOBs (iob.js): O and T mux with codes, input pips; pad -> CLB pin is recorded in pad_of_clb"""
        self.iobs = iobmux.iobs(self.lines, self.entries)
        self.clkmuxes = iobmux.clkmuxes(self.lines, self.entries)
        pip_bit = {e.key[0]: e.index for e in self.entries if e.kind == "pip"}
        # inputs of the pads into the clock buffers: in iob.js crossings without a PIP bit or @aclk_in (_clkbufs)
        clk_in = {(s.special, s.g) for cm in self.clkmuxes.values() for s in cm.sources if s.kind == "pad"}
        self.pad_of_clb = {}  # (CLB pin, side T/L/B) -> pin of the pad
        for pin, iob in sorted(self.iobs.items()):
            for which, lst, codes, bits in (("O", iob.o, iob.omux, iob.obits), ("T", iob.t, iob.tmux, iob.tbits)):
                bitl = [bits[n] for n in sorted(bits)]
                for code, k in sorted(codes.items()):
                    ent = lst[k]
                    src = self.iob_source(ent)
                    if src is None:
                        self.unmodelled.append((pin, ent.spec, "source of the %s mux" % which))
                        continue
                    self.conns.append(Conn("iob" + which.lower(), src, "%s.%s" % (pin, which), bitl, code,
                                           "%s.%s %s" % (pin, which, iobmux.source_name(ent))))
            for ent in iob.i:
                if ent.kind == "clb":
                    self.pad_of_clb[(ent.special, iob.style[0].upper())] = pin
                    continue
                if ent.kind == "aclk_in" or (pin, ent.g) in clk_in:
                    continue
                bit = pip_bit.get(ent.g)
                if ent.kind != "route" or not self._route_ok(ent) or bit is None:
                    self.unmodelled.append((pin, ent.spec, "input (%s)" % (ent.kind if bit else "no PIP bit")))
                    continue
                self.conns.append(Conn("iobi", "%s.I" % pin, self.route_node(ent), [bit], None,
                                       "%s:%s" % (ent.col, ent.row)))

    def _iob_clocks(self):
        """Clocks of the latched inputs: K muxes (iobmux.kmuxes) onto the clock line of their side, each IOB
        hardwired to the line of its side. Sources that are not routing lines (stubs) go into unmodelled."""
        self.kmuxes = iobmux.kmuxes(self.lines, self.entries)
        self.latch_bit = {}  # pin -> bit "I PAD/Latched" (programmed: direct, otherwise latched)
        for e in self.entries:
            m = re.fullmatch(r"IOB (P\d+)\.I PAD/Latched", e.text)
            if m:
                self.latch_bit[m[1]] = e.index
        for pin, km in sorted(self.kmuxes.items()):
            bits = [km.bits[n] for n in sorted(km.bits)]
            for code, k in sorted(km.codes.items()):
                ent = km.sources[k]
                src = self.iob_source(ent)
                if src is None:
                    self.unmodelled.append((pin, ent.spec, "source of the K mux"))
                    continue
                self.conns.append(Conn("iobk", src, "IOCLK." + km.side, bits, code,
                                       "%s.K %s" % (pin, iobmux.source_name(ent))))
        for pin, iob in sorted(self.iobs.items()):
            self.conns.append(Conn("iobkin", "IOCLK." + iob.style[0].upper(), pin + ".K", [], None, pin + ".K"))

    def latched(self, pin, raw):
        """Is the input of the IOB latched (I:Q) in the bitstream raw?"""
        return raw[self.latch_bit[pin]] == 1

    def cfg(self, cn):
        """Line in the text format (config.py) that programs this connection; None for the buffers (bidi) and
        fixed connections (iobkin)"""
        if cn.kind in ("pip", "out", "clkout", "junction", "iobi"):
            return "pip " + self.lines.pip_name(self.entries[cn.bits[0]].key[0])
        if cn.kind == "switch":
            return "switch " + cn.name
        if cn.kind in ("mux", "iobo", "iobt", "iobk", "clkbuf"):
            return "mux " + cn.name
        return None

    def _route_ok(self, ent):
        kind, letter, rest = _split(ent.line)
        return self._general_col(letter, rest) if kind == "col" else self._general_row(letter, rest)

    def route_node(self, ent):
        gx, gy = (int(v) for v in ent.g.split("G"))
        return self.seg_col(ent.line, gy) if ent.line.startswith("col.") else self.seg_row(ent.line, gx)

    def iob_source(self, ent):
        if ent.kind == "route":
            return self.route_node(ent) if self._route_ok(ent) else None
        if ent.kind in ("x", "y"):
            return "%s.%s" % (ent.special, ent.kind.upper())
        if ent.kind == "gclk":
            return "GCLK"
        return None

    def _muxes(self):
        ln = self.lines
        self.muxes = clbmux.muxes(ln, self.entries)
        for name, m in sorted(self.muxes.items()):
            r, c = m.tile
            sink = "%s.%s" % (m.tile, m.pin)
            for code, i in sorted(m.codes.items()):
                if i is None:
                    continue
                s = m.sources[i]
                gx, gy = (int(v) for v in s.g.split("G"))
                bits = [m.bits[n] for n in sorted(m.bits)]
                src = self.mux_source(m, s, gx, gy)
                if src.startswith("pad:"):  # pad at the edge: its input (iob.js)
                    pin = self.pad_of_clb.get((sink, src[4]))
                    if pin is None:
                        self.unmodelled.append((sink, s.name, "no pad"))
                        continue
                    src = pin + ".I"
                self.conns.append(Conn("mux", src, sink, bits, code, "%s %s" % (sink, s.line)))

    def _clkbufs(self):
        """Clock buffers (datasheet Figure 8b): GCLK at the top left drives CLK.AA.O and col.*.clk, ACLK at the
        bottom right row.I.clk. Their input muxes CLK.AA.I (6 bits) and CLK.II.I (8 bits) with sources and codes
        from iobmux.clkmuxes (determined with MAKEBITS): lines at the edge, the pads P9/P11 or P43/P46. The
        crystal oscillator (source of ACLK) has no Bel and is listed in unmodelled."""
        for name, cm in sorted(self.clkmuxes.items()):
            bits = [cm.bits[n] for n in sorted(cm.bits)]
            for code, k in sorted(cm.codes.items()):
                ent = cm.sources[k]
                if ent.kind == "route":
                    src = self.route_node(ent)
                elif ent.kind == "pad":
                    src = ent.special + ".I"
                else:
                    self.unmodelled.append((name, ent.spec, "source of the clock buffer (oscillator, no Bel)"))
                    continue
                self.conns.append(Conn("clkbuf", src, cm.net, bits, code,
                                       "%s %s" % (name, iobmux.source_name(ent))))

    def mux_source(self, m, s, gx, gy):
        r, c = m.tile
        _, _, kind = _split(s.line)
        if kind == "local.6":  # Y of the CLB to the left -> B
            return "%s%s.Y" % (r, _prev(c))
        if kind == "x":  # X of the CLB above -> B, X of the CLB below -> C
            if m.pin == "B":
                return "pad:T" if r == "A" else "%s%s.X" % (_prev(r), c)
            return "pad:B" if r == "H" else "%s%s.X" % (_next(r), c)
        if kind == "io4":
            return "%s%s.X" % (_prev(r), c)
        if kind == "io3" and m.pin == "D":
            return "%s%s.X" % (_next(r), c)
        if kind == "io3":  # column A, B: pad on the left
            return "pad:L"
        if kind == "io2":  # A at the top or D at the bottom: pad
            return "pad:T" if m.pin == "A" else "pad:B"
        if kind == "clk":
            return "GCLK"
        if s.line.startswith("col."):
            return self.seg_col(s.line, gy)
        return self.seg_row(s.line, gx)

    # --- Check of the buffer direction ---------------------------------------------------------
    def bidi_check(self, raw):
        """Direction of the repowering buffers in a bitstream (only in the check mode split_bidi): for each used
        buffer the bit must match the code of the direction in which the signal runs (bidi_directions).
        Result: count of matches, list of contradictions (name, bit, direction)."""
        ok, bad = 0, []
        for down, code in self.bidi_directions(raw):
            if code is None:
                continue
            if raw[down.bits[0]] == code:
                ok += 1
            else:
                bad.append((down.name, raw[down.bits[0]], "down/right" if code == down.code else "up/left"))
        return ok, bad

    def bidi_directions(self, raw):
        """Per buffer (split_bidi only): (connection down/right, code of the signal's direction or None).
        Without the buffer its net splits into two sides; if the driver (X/Y, Pnn.I) is on one side, the buffer
        points away from it, even if no sink hangs on the other side (otherwise it would drive into the net
        like a second driver; MAKEBITS sets it the same way). None: no driver on either side (any
        direction). Drivers on both sides: ValueError."""
        assert self.split_bidi
        edges, bufs = [], {}
        for cn in self.conns:
            if cn.kind == "bidi":
                bufs.setdefault(cn.name, []).append(cn)
            elif conn_on(cn, raw):
                edges.append((cn.a, cn.b))
        all_buf = [(c[0].a, c[0].b) for c in bufs.values()]

        def is_driver(n):
            return re.fullmatch(r"[A-H][A-H]\.[XY]|P\d+\.I", n)

        out = []
        for name, (down, up) in sorted(bufs.items()):
            parent = {}

            def find(n):
                parent.setdefault(n, n)
                while parent[n] != n:
                    parent[n] = parent[parent[n]]
                    n = parent[n]
                return n
            for a, b in edges + [e for e in all_buf if e != (down.a, down.b)]:
                parent[find(a)] = find(b)
            if find(down.a) == find(down.b):
                out.append((down, None))  # loop via another path (does not occur in the bitstreams)
                continue
            sides = [[n for n in parent if find(n) == find(x)] for x in (down.a, down.b)]
            drv = [any(is_driver(n) for n in s) for s in sides]
            if drv[0] and drv[1]:
                raise ValueError("Buffer %s: drivers on both sides" % name)
            if drv[0]:
                out.append((down, down.code))
            elif drv[1]:
                out.append((down, up.code))
            else:
                out.append((down, None))  # no driver: any direction
        return out

    # --- Queries -------------------------------------------------------------------------------
    def nodes(self):
        n = set()
        for cn in self.conns:
            n.add(cn.a)
            n.add(cn.b)
        return n

    def by_bit(self):
        """Bit number -> list of the connections that use this bit"""
        d = collections.defaultdict(list)
        for cn in self.conns:
            for b in cn.bits:
                d[b].append(cn)
        return d
