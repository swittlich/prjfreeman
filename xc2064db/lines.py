"""Line names and their positions from Shirriff's draw.js.

Every vertical line is named col.<column>.<kind>, every horizontal one row.<row>.<kind> (columns and rows
A-I like the tiles AA..II). Each has two coordinates: G (the position in the bitstream grid, which the PIP
entries of the bit map also use, e.g. "170G23" = column G 170, row G 23) and the screen position in
Shirriff's viewer. A PIP is the crossing of a col line with a row line.

The edges (columns A and I, rows A and I) are tables in draw.js and are read as text; the columns and rows
B-H are computed by initNames(). These formulas are reproduced here. Names that Shirriff assigned himself
("My invention", e.g. io1-io6, clbl/clbr) are lines in the chip, just without names from the original.
Aliases such as "AB.B" (the row through input B of the CLB AB) exist as in draw.js.
"""
import re

from . import sources

# initNames(): offset of the G coordinate from cstart = 27 + 20 * (i - 1) or rstart = 25 + 19 * (7 - i), and
# screen position 'base + 72 * (i - 1)' for the columns and rows B-H (i = 1..7)
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
        raise ValueError("draw.js: table %s not found" % var)
    table = {}
    for line in block.group(1).splitlines():
        line = line.split("//")[0]
        m = re.search(r'"([^"]+)":\s*\[(-?\d+),\s*(-?\d+)\]', line)
        if m:
            table[m[1]] = (int(m[2]), int(m[3]))
    return table


class Lines:
    """col_info/row_info: name -> (G, screen) as in draw.js; col_name/row_name: G -> name without alias"""

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
        # aliases per CLB, as at the end of initNames()
        for r in "ABCDEFGH":
            for c in "ABCDEFGH":
                t = r + c
                for pin, line in (("B", "b"), ("C", "c"), ("K", "k"), ("X", "c"), ("Y", "y")):
                    self.row_info[t + "." + pin] = self.row_info["row.%s.%s" % (r, line)]
                self.col_info[t + ".D"] = self.col_info["col.%s.clb" % c]
                self.col_info[t + ".A"] = self.col_info["col.%s.clbr1" % c]

    @staticmethod
    def _by_g(info):
        """G -> name. According to draw.js, clbw1-3 of a column are the same lines as clbr1-3 of the column
        to the left (for the assignment of the IOBs); then the clbr name applies, clbw remains an alias in
        col_info."""
        by_g = {}
        for name, (g, _) in info.items():
            if g == 999:  # placeholder in draw.js ("col.I.clb")
                continue
            if g in by_g:
                old = by_g[g]
                if ".clbw" in name and ".clbr" in old:
                    continue
                if ".clbw" in old and ".clbr" in name:
                    by_g[g] = name
                    continue
                raise ValueError("two lines with G %d: %s and %s" % (g, old, name))
            by_g[g] = name
        return by_g

    def pip_name(self, g):
        """'170G23' -> 'col.I.long.2:row.?' (crossing as col:row), None if one side is unknown"""
        x, y = (int(v) for v in g.split("G"))
        col, row = self.col_name.get(x), self.row_name.get(y)
        return "%s:%s" % (col, row) if col and row else None

    def canonical_col(self, name):
        """Alias (e.g. 'AB.A') -> line name"""
        return self.col_name[self.col_info[name][0]]

    def canonical_row(self, name):
        return self.row_name[self.row_info[name][0]]
