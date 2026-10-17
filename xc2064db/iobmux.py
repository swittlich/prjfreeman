"""IOBs: Quellen des Ausgangs-Mux (O, bei XACT "Pnn.O"), des Tristate-Mux (T) mit ihren Codes und die
Pips des Eingangs (I) auf die Leitungen, nachgebildet aus Shirriffs iob.js (generateIobPips).

Ein Eintrag in iob.js ist die Kreuzung einer Stichleitung des IOB mit einer Leitung: "|col.?.x:row.A.local.2"
(senkrechte Stichleitung col.?.x des IOB, Routing-Leitung row.A.local.2) bzw. "-col.?.long.1:row.A.io3"
(waagerechte Stichleitung, Routing-Leitung col.?.long.1); "?" ist die Spalte bzw. Zeile der Kachel.
Einträge ohne | oder - sind Direktverbindungen (X/Y einer CLB, Taktleitungen, Pad -> CLB-Pin).

Die Stichleitungen am Rand (io1-io6, x, clbl, clbr, clbw, local.0, local.5 der Randzeilen und -spalten) sind
Teile des IOB, keine Routing-Leitungen. Die O- und T-Muxe sind kodiert (Bits "IOB Pnn.O/T MuxBit"), der Code
der T-Bits wählt zugleich den Modus: Tristate mit Quelle, aus (Ausgang nie aktiv) oder an (immer aktiv).

Takt der gelatchten Eingänge (Data Book: die IOBs einer Chipseite teilen sich einen Takt): je Seite eine
Taktleitung, an der jedes IOB der Seite fest hängt (iob.js: kin), getrieben von einem K-Mux an einer Ecke mit
Quellen aus dem Randkanal derselben Seite. Die Bitkarte ordnet die 4 Bits jedes K-Muxes einem Pad zu ("IOB
P9.K MuxBit", P9 oben, P59 rechts, P27 unten, P24 links), Codes aus iob.js (generateIobPips).
"""
import collections
import re

from . import sources

Entry = collections.namedtuple("Entry", "index spec kind line col row g special")
# kind: route (Routing-Leitung line), x/y (X bzw. Y der CLB special), gclk, aclk_in (P43 -> ACLK-Puffer),
#       clb (Pad -> CLB-Pin special), stub (Stichleitung eines IOB special, Signal unbekannt)

# K-Muxe: Pad der Bits -> (Seite, Stichleitung des Muxes an der Ecke, Quellen in der Reihenfolge von iob.js,
# Code -> Index). "@gclk" ist CLK.AA.O bzw. col.A.clk (GCLK), "@stub:..." eine IOB-Stichleitung unbekannter
# Herkunft.
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


class Iob:
    def __init__(self, pin, tile, style, pad):
        self.pin, self.tile, self.style, self.pad = pin, tile, style, pad
        self.o, self.i, self.t = [], [], []  # Listen von Entry
        self.omux = {}  # Code -> Index in o
        self.tmux = {}  # Code -> Index in t (Tristate)
        self.t_off = self.t_on = None  # Codes: Ausgang aus bzw. immer an
        self.obits, self.tbits = {}, {}  # n -> Bitnummer


def pads():
    """Pad-Tabelle aus iob.js: [(Pin, Kachel, Art, PADn)]"""
    js = sources.read_text(sources.IOB_JS)
    return re.findall(r'\["(P\d+)",\s*"([A-I][A-I])",\s*"(\w+)",\s*"(PAD\d+)"\]', js)


def _lists(pin, tile, d):
    """o, i, t, omux, (tmux, t_off, t_on) wie in generateIobPips"""
    r, c = tile
    prev_r, prev_c = chr(ord(r) - 1), chr(ord(c) - 1)
    std_t_top = {3: 0, 1: 1, 7: 2, 5: 3}
    if d == "topleft":
        t = ["|col.?.clbl1:row.A.long.2", "|col.?.clbl1:row.A.local.1", "|col.?.clbl1:row.A.local.3",
             "|col.?.clbl1:row.A.long.3"]
        tm = (std_t_top, 4, 6)
        if tile == "AA":
            o = ["@gclk", "|col.?.io3:row.A.long.2", "|col.?.io3:row.A.local.2", "|col.?.io3:row.A.local.4",
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
                 "@x:AH", "-col.I.long.1:row.?.io3", "-col.I.local.1:row.?.io3", "-col.I.local.3:row.?.io3",
                 "-col.I.long.3:row.?.io3"]
            i = ["|col.?.clbw2:row.A.long.2", "|col.?.clbw2:row.A.local.2", "|col.?.clbw2:row.A.local.4",
                 "-col.I.long.2:row.?.io2", "-col.I.local.2:row.?.io2", "-col.I.local.4:row.?.io2",
                 "-col.I.long.3:row.?.io2"]
        else:
            o = ["|col.?.clbw1:row.A.local.1", "|col.?.clbw1:row.A.local.3", "|col.?.clbw1:row.A.long.3",
                 "@x:A%s" % prev_c, "-col.?.local.2:row.A.io2", "-col.?.local.4:row.A.io2",
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
             "@x:%sH" % prev_r, "@y:%sH" % prev_r]
        om = {6: 0, 30: 1, 20: 2, 21: 3, 19: 4, 18: 5, 7: 6, 31: 7}
    elif d == "rightupper":
        t = ["-col.I.long.3:row.?.io4", "-col.I.local.4:row.?.io4", "-col.I.local.2:row.?.io4",
             "-col.I.long.2:row.?.io4"]
        tm = ({5: 0, 3: 1, 7: 2, 1: 3}, 6, 4)
        i = ["-col.I.local.4:row.?.io5", "-col.I.local.2:row.?.io5", "-col.I.long.2:row.?.io5",
             "|col.I.io3:row.?.long.1", "|col.I.io3:row.?.local.4", "|col.I.io3:row.?.local.1"]
        o = ["-col.I.long.3:row.?.io6", "-col.I.local.3:row.?.io6", "-col.I.local.1:row.?.io6",
             "-col.I.long.1:row.?.io6", "|col.I.local.0:row.?.local.5", "|col.I.local.0:row.?.local.3",
             "@x:%sH" % r, "@y:%sH" % r]
        om = {31: 0, 25: 1, 21: 2, 13: 3, 12: 4, 24: 5, 20: 6, 30: 7}
    elif d == "bottomright":
        t = ["|col.?.clbw3:row.I.long.2", "|col.?.clbw3:row.I.local.4", "|col.?.clbw3:row.I.local.2",
             "|col.?.clbw3:row.I.long.1"]
        tm = (std_t_top, 6, 4)
        if tile == "II":
            o = ["|col.?.clbw1:row.I.clk", "|col.?.clbw1:row.I.local.4", "|col.?.clbw1:row.I.local.2",
                 "|col.?.clbw1:row.I.long.1", "-col.?.long.2:row.I.io2", "-col.?.local.2:row.I.io2",
                 "-col.?.local.4:row.I.io2", "-col.?.long.3:row.I.io2", "@x:HH"]
            i = ["|col.?.clbw2:row.I.long.2", "|col.?.clbw2:row.I.local.3", "|col.?.clbw2:row.I.local.1",
                 "@aclk_in", "-col.?.long.1:row.I.io3", "-col.?.local.1:row.I.io3", "-col.?.local.3:row.I.io3",
                 "-col.?.long.3:row.I.io3"]
            om = {14: 0, 45: 1, 42: 2, 43: 3, 39: 4, 62: 5, 38: 6, 63: 7, 44: 8}
        else:
            o = ["|col.?.clbw1:row.I.local.4", "|col.?.clbw1:row.I.local.2", "|col.?.clbw1:row.I.long.1",
                 "-col.?.local.2:row.I.io3", "-col.?.local.4:row.I.io3", "-col.?.local.5:row.I.io3",
                 "-col.?.long.2:row.I.io3", "@x:H%s" % prev_c]
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
        raise ValueError("unbekannte IOB-Art %s" % d)
    return o, i, t, om, tm


def _entry(idx, spec, tile, lines):
    """Ein Eintrag aus iob.js -> Entry (Routing-Leitung oder Sonderfall)"""
    if spec.startswith("@"):
        kind, _, arg = spec[1:].partition(":")
        return Entry(idx, spec, kind, None, None, None, None, arg or None)
    d, a, b = spec[0], *spec[1:].split(":")
    col = a.replace("?", tile[1], 1)
    row = b.replace("?", tile[0], 1)
    g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
    col, row = lines.canonical_col(col), lines.canonical_row(row)
    line = row if d == "|" else col
    return Entry(idx, spec, "route", line, col, row, g, None)


def iobs(lines, entries):
    """Pin -> Iob für alle 58 Pads, mit Bits aus der Bitkarte"""
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
                raise ValueError("%s.%s: Mux-Bits %s nicht lückenlos" % (iob.pin, name, sorted(bits)))
            bad = [c for c in codes if c >= 1 << len(bits)]
            if bad:
                raise ValueError("%s.%s: Codes %s passen nicht in %d Bits" % (iob.pin, name, bad, len(bits)))
    return result


def kmuxes(lines, entries):
    """Pad der Bits -> KMux (Quellen als Entry an der Kreuzung mit der Stichleitung, bits: n -> Bitnummer)"""
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
                sources.append(Entry(k, spec, kind, None, None, None, None, arg or None))
                continue
            col, row = (stub, spec) if stub.startswith("col.") else (spec, stub)
            g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
            col, row = lines.canonical_col(col), lines.canonical_row(row)
            sources.append(Entry(k, spec, "route", row if stub.startswith("col.") else col, col, row, g, None))
        if sorted(bits[pin]) != [0, 1, 2, 3] or any(c >= 16 for c in codes):
            raise ValueError("%s.K: Mux-Bits %s bzw. Codes passen nicht" % (pin, sorted(bits[pin])))
        result[pin] = KMux(pin, side, stub, sources, codes, bits[pin])
    return result


def code(bits, raw):
    return sum(raw[b] << n for n, b in bits.items())


def source_name(ent):
    """Name einer Quelle des O-, T- bzw. K-Mux im Textformat: Leitung, X/Y einer CLB, GCLK oder Stichleitung"""
    if ent.kind == "route":
        return ent.line
    if ent.kind in ("x", "y"):
        return "%s.%s" % (ent.special, ent.kind.upper())
    if ent.kind == "stub":
        return ent.special
    return ent.kind.upper()
