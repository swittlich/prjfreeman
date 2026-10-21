# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
"""CLB inputs A, B, C, D and K: the sources of each input mux and which mux code selects which source,
modelled on Shirriff's clb.js (generateClbPips, processClbPip).

A source is a crossing of two lines: the input line of the CLB (A and D vertical, B, C and K
horizontal) with the line the signal comes from (line). The code is the raw value of the mux bits with
bit n = 2^n (as in clb.js); a code without a source is "not connected" (only for K).

clb.js writes the placeholders as follows: "=" is the row or column of the tile, "==" the tile, "-=" and
"+=" the tile above or below, "=-" and "=+" (only for names) left and right. As in JavaScript,
replace() replaces only the first occurrence each time.
"""
import collections

Source = collections.namedtuple("Source", "index line col row g name")


class Mux:
    def __init__(self, tile, pin, sources, codes):
        self.tile, self.pin = tile, pin
        self.sources = sources  # list of Source, index = position in clb.js
        self.codes = codes  # code -> index in sources or None (not connected)
        self.bits = {}  # n -> bit number, from the bit map

    @property
    def name(self):
        return "%s.%s" % (self.tile, self.pin)

    def code(self, raw):
        return sum(raw[b] << n for n, b in self.bits.items())

    def decode(self, raw):
        """(code, Source or None); KeyError for an unknown code"""
        c = self.code(raw)
        i = self.codes[c]
        return c, (None if i is None else self.sources[i])


def _expand(spec, tile):
    r, c = tile
    prev_r, next_r, next_c = chr(ord(r) - 1), chr(ord(r) + 1), chr(ord(c) + 1)
    s = spec.replace("==", tile, 1).replace("-=", prev_r + c, 1).replace("+=", next_r + c, 1)
    s = s.replace("=-", r + prev_r, 1).replace("=+", r + next_r, 1)
    parts = s.split(":")
    if parts[0].startswith("col") or parts[1].startswith("row"):
        col, row = parts[0], parts[1]
    elif parts[0].startswith("row") or parts[1].startswith("col"):
        row, col = parts[0], parts[1]
    else:
        raise ValueError("clb.js: unexpected pip %s" % spec)
    row = row.replace("=", r, 1).replace("+", next_r, 1)
    col = col.replace("=", c, 1).replace("+", next_c, 1)
    name = parts[2] + ":" + parts[3] if len(parts) == 4 else col + ":" + row
    return col, row, name


def _specs(tile):
    """Sources (clb.js notation) and codes per input, case distinction as in generateClbPips"""
    r, c = tile
    s = {}
    if r == "A":
        pad = {"A": 1, "B": 3, "C": 5, "D": 7, "E": 9, "F": 11, "G": 13, "H": 15}[c]
        s["A"] = (["row.A.long.2:col.=.clb:row.A.long.2:==.A", "row.A.local.1:col.=.clb:row.A.local.1:==.A",
                   "row.A.local.2:col.=.clb:row.A.local.2:==.A", "row.A.local.3:col.=.clb:row.A.local.3:==.A",
                   "row.A.local.4:col.=.clb:row.A.local.4:==.A", "row.A.long.3:col.=.clb:row.A.long.3:==.A",
                   "row.A.io2:col.=.clb::==.A:PAD%d.I" % pad],
                  {30: 0, 13: 1, 24: 2, 12: 3, 21: 4, 25: 5, 31: 6})
    else:
        s["A"] = (["row.=.local.1:==.A", "row.=.local.3:==.A", "row.=.local.4:==.A", "row.=.local.5:==.A",
                   "row.=.long.1:==.A", "==.A:row.=.io4"],
                  {3: 0, 15: 1, 4: 2, 2: 3, 14: 4, 5: 5})

    if c == "A":
        pad = {"A": 58, "B": 56, "C": 54, "D": 52, "E": 51, "F": 49, "G": 47, "H": 46}[c]  # as in clb.js: always 58
        b = ["col.=.long.2:==.B", "col.=.local.1:==.B", "col.=.local.2:==.B", "col.=.local.3:==.B",
             "col.=.local.4:==.B", "col.=.long.3:==.B", "col.=.long.4:==.B", "col.=.clk:==.B:CLK.AA.O:==.B",
             "col.=.io3:==.B:PAD%d.I:==.B" % pad,
             "col.=.x:==.B:PAD1.I:==.B" if tile == "AA" else "col.=.x:==.B:-=.X:==.B"]
        if tile == "AA":
            bmux = {15: 0, 22: 1, 26: 2, 28: 3, 63: 4, 23: 5, 27: 6, 29: 7, 14: 8, 62: 9}
        else:
            bmux = {22: 0, 15: 1, 28: 2, 63: 3, 23: 4, 26: 5, 27: 6, 29: 7, 14: 8, 62: 9}
    else:
        b = ["col.=.local.1:==.B", "col.=.local.2:==.B", "col.=.local.3:==.B", "col.=.local.4:==.B",
             "col.=.local.5:==.B", "col.=.local.6:==.B:=-.X:==.A", "col.=.long.1:==.B", "col.=.long.2:==.B",
             "col.=.clk:==.B:CLK.AA.O:==.B", "col.=.x:==.B:-=.X:==.B"]
        if r == "A":
            bmux = {22: 0, 26: 1, 28: 2, 63: 3, 15: 4, 14: 5, 23: 6, 27: 7, 29: 8, 62: 9}
        else:
            bmux = {15: 0, 28: 1, 63: 2, 23: 3, 22: 4, 14: 5, 26: 6, 27: 7, 29: 8, 62: 9}
    s["B"] = (b, bmux)

    if c == "A":
        cc = ["col.=.long.2:==.C", "col.=.local.1:==.C", "col.=.local.2:==.C", "col.=.local.3:==.C",
              "col.=.local.4:==.C", "col.=.long.3:==.C", "col.=.long.4:==.C",
              "col.=.x:==.C:PAD45.I:==.C" if tile == "HA" else "col.=.x:==.C:+=.X:==.C"]
        if tile == "AA":
            cmux = {6: 0, 7: 1, 11: 2, 13: 3, 30: 4, 10: 5, 12: 6, 31: 7}
        else:
            cmux = {7: 0, 12: 1, 13: 2, 30: 3, 6: 4, 11: 5, 10: 6, 31: 7}
    else:
        cc = ["col.=.local.1:==.C", "col.=.local.2:==.C", "col.=.local.3:==.C", "col.=.local.4:==.C",
              "col.=.local.5:==.C", "col.=.long.1:==.C", "col.=.long.2:==.C", "col.=.x:==.C:-=.X:==.C"]
        if r == "A":
            cmux = {7: 0, 11: 1, 13: 2, 30: 3, 6: 4, 10: 5, 12: 6, 31: 7}
        else:
            cmux = {12: 0, 13: 1, 30: 2, 6: 3, 7: 4, 11: 5, 10: 6, 31: 7}
    s["C"] = (cc, cmux)

    k = ["col.=.long.4:==.K" if c == "A" else "col.=.long.2:==.K", "col.=.clk:==.K:CLK.AA.O:==.K"]
    s["K"] = (k, {2: 0, 1: 1, 3: None})  # 3: not connected

    if r == "H":
        pad = {"A": 45, "B": 43, "C": 41, "D": 39, "E": 37, "F": 35, "G": 33, "H": 31}[c]
        s["D"] = (["row.+.io2:==.D:==.D:PAD%d.I" % pad, "row.+.long.1:==.D", "row.+.local.1:==.D",
                   "row.+.local.2:==.D", "row.+.local.3:==.D", "row.+.local.4:==.D", "row.+.long.2:==.D"],
                  {31: 0, 25: 1, 21: 2, 12: 3, 24: 4, 13: 5, 30: 6})
    else:
        s["D"] = (["row.+.io3:==.D:==.D:+=.X", "row.+.local.1:==.D", "row.+.local.3:==.D", "row.+.local.4:==.D",
                   "row.+.local.5:==.D", "row.+.long.1:==.D"],
                  {5: 0, 3: 1, 15: 2, 4: 3, 2: 4, 14: 5})
    return s


def muxes(lines, entries):
    """Name 'AB.A' -> Mux for all 64 CLBs and the inputs A, B, C, D, K"""
    result = {}
    for r in "ABCDEFGH":
        for c in "ABCDEFGH":
            tile = r + c
            for pin, (specs, codes) in _specs(tile).items():
                sources = []
                for i, spec in enumerate(specs):
                    col, row, name = _expand(spec, tile)
                    col_c, row_c = lines.canonical_col(col), lines.canonical_row(row)
                    g = "%dG%d" % (lines.col_info[col][0], lines.row_info[row][0])
                    line = row_c if pin in "AD" else col_c
                    sources.append(Source(i, line, col_c, row_c, g, name))
                result["%s.%s" % (tile, pin)] = Mux(tile, pin, sources, codes)
    for e in entries:
        if e.kind == "clbmux":
            tile, pin, n = e.key
            result["%s.%s" % (tile, pin)].bits[n] = e.index
    for m in result.values():
        width = max(m.bits) + 1
        if sorted(m.bits) != list(range(width)):
            raise ValueError("%s: mux bits %s not contiguous" % (m.name, sorted(m.bits)))
        bad = [code for code in m.codes if code >= 1 << width]
        if bad:
            raise ValueError("%s: codes %s do not fit in %d bits" % (m.name, bad, width))
    return result
