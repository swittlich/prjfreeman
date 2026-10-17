"""Leitungsnamen und ihre Lage aus Shirriffs draw.js.

Jede senkrechte Leitung heißt col.<Spalte>.<Art>, jede waagerechte row.<Zeile>.<Art> (Spalten und Zeilen
A-I wie die Kacheln AA..II). Dazu gehören zwei Koordinaten: G (die Lage im Bitstream-Raster, in der auch
die PIP-Einträge der Bitkarte stehen, z. B. "170G23" = Spalte G 170, Zeile G 23) und die Bildschirmlage in
Shirriffs Viewer. Ein PIP ist die Kreuzung einer col- mit einer row-Leitung.

Die Ränder (Spalten A und I, Zeilen A und I) stehen in draw.js als Tabellen und werden als Text gelesen,
die Spalten und Zeilen B-H rechnet initNames() aus. Diese Formeln sind hier nachgebildet. Namen, die
Shirriff selbst vergeben hat ("My invention", z. B. io1-io6, clbl/clbr), sind Leitungen im Chip, nur ohne
Namen aus dem Original. Aliasse wie "AB.B" (die Zeile durch Eingang B der CLB AB) gibt es wie in draw.js.
"""
import re

from . import sources

# initNames(): Versatz der G-Koordinate gegen cstart = 27 + 20 * (i - 1) bzw. rstart = 25 + 19 * (7 - i) und
# Bildschirmlage 'Basis + 72 * (i - 1)' für die Spalten und Zeilen B-H (i = 1..7)
_COLS = [("clbw1", -5, 94), ("clbw2", -4, 98), ("clbw3", -3, 102), ("local.1", 0, 108), ("local.2", 1, 112),
         ("local.3", 3, 116), ("local.4", 4, 120), ("local.5", 6, 126), ("local.6", 7, 130), ("long.1", 8, 134),
         ("long.2", 9, 138), ("clk", 10, 142), ("x", 11, 146), ("clbl2", 12, 150), ("clbl1", 13, 154),
         ("clb", 14, 160), ("clbr1", 15, 166), ("clbr2", 16, 170), ("clbr3", 17, 174)]
_ROWS = [("io1", 11, 100), ("io2", 10, 104), ("io3", 9, 108), ("local.0", 7, 112), ("local.1", 6, 114),
         ("local.3", 5, 118), ("local.4", 3, 122), ("local.5", 2, 126), ("long.1", 0, 132), ("io4", -1, 136),
         ("io5", -2, 140), ("io6", -3, 144), ("b", -4, 152), ("c", -5, 158), ("k", -6, 164), ("y", -7, 168)]


def _literal(js, var):
    block = re.search(r"var %s = \{(.*?)\n\}" % var, js, re.S)
    if not block:
        raise ValueError("draw.js: Tabelle %s nicht gefunden" % var)
    table = {}
    for line in block.group(1).splitlines():
        line = line.split("//")[0]
        m = re.search(r'"([^"]+)":\s*\[(-?\d+),\s*(-?\d+)\]', line)
        if m:
            table[m[1]] = (int(m[2]), int(m[3]))
    return table


class Lines:
    """col_info/row_info: Name -> (G, Bildschirm) wie in draw.js; col_name/row_name: G -> Name ohne Alias"""

    def __init__(self, path=sources.DRAW_JS):
        js = sources.read_text(path)
        self.col_info, self.row_info = _literal(js, "colInfo"), _literal(js, "rowInfo")
        for i in range(1, 8):
            name = "ABCDEFGHI"[i]
            cstart, rstart = 27 + 20 * (i - 1), 25 + 19 * (7 - i)
            for sfx, off, base in _COLS:
                self.col_info["col.%s.%s" % (name, sfx)] = (cstart + off, base + 72 * (i - 1))
            for sfx, off, base in _ROWS:
                self.row_info["row.%s.%s" % (name, sfx)] = (rstart + off, base + 72 * (i - 1))
        self.col_name = self._by_g(self.col_info)
        self.row_name = self._by_g(self.row_info)
        # Aliasse je CLB, wie am Ende von initNames()
        for r in "ABCDEFGH":
            for c in "ABCDEFGH":
                t = r + c
                for pin, line in (("B", "b"), ("C", "c"), ("K", "k"), ("X", "c"), ("Y", "y")):
                    self.row_info[t + "." + pin] = self.row_info["row.%s.%s" % (r, line)]
                self.col_info[t + ".D"] = self.col_info["col.%s.clb" % c]
                self.col_info[t + ".A"] = self.col_info["col.%s.clbr1" % c]

    @staticmethod
    def _by_g(info):
        """G -> Name. clbw1-3 einer Spalte sind laut draw.js dieselben Leitungen wie clbr1-3 der Spalte
        links (für die Zuordnung der IOBs); dann gilt der clbr-Name, clbw bleibt Alias in col_info."""
        by_g = {}
        for name, (g, _) in info.items():
            if g == 999:  # Platzhalter in draw.js ("col.I.clb")
                continue
            if g in by_g:
                old = by_g[g]
                if ".clbw" in name and ".clbr" in old:
                    continue
                if ".clbw" in old and ".clbr" in name:
                    by_g[g] = name
                    continue
                raise ValueError("zwei Leitungen mit G %d: %s und %s" % (g, old, name))
            by_g[g] = name
        return by_g

    def pip_name(self, g):
        """'170G23' -> 'col.I.long.2:row.?' (Kreuzung als col:row), None wenn eine Seite unbekannt ist"""
        x, y = (int(v) for v in g.split("G"))
        col, row = self.col_name.get(x), self.row_name.get(y)
        return "%s:%s" % (col, row) if col and row else None

    def canonical_col(self, name):
        """Alias (z. B. 'AB.A') -> Leitungsname"""
        return self.col_name[self.col_info[name][0]]

    def canonical_row(self, name):
        return self.row_name[self.row_info[name][0]]
