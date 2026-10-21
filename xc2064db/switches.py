# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
"""Switch matrices: two per tile crossing (XY.8.1 and XY.8.2), none at the four corners of the chip.
Each has 8 pins, 1-2 top, 3-4 right, 5-6 bottom, 7-8 left (draw.js, Switch.pinCoord). Every possible
connection of two pins is a Magic bit of the bit map.

The position (G coordinate under which the Magic bits are listed): matrix 1 at local.1 of the column, matrix 2
three columns further (local.3); mirrored in row I. For row I, XACT's naming applies (TEST1.LCA: IB.8.2.0 is
at 30G11), as in Shirriff's getSwitchCoords(); his Switch class swaps 8.1 and 8.2 there.

Pins: pin n (1-8) here and in the Magic bits is pin n-1 in XACT (TEST1.LCA: AB.8.1.6/AB.8.1.4 is the
Magic bit "AB.8.1 5 7"). Pin p (0-7 in XACT) lies at gPt + (DX[p], DY[p]) in G coordinates.
"""
import collections

LETTERS = "ABCDEFGHI"
DX = [0, 1, 2, 2, 1, 0, -1, -1]
DY = [0, 0, -1, -2, -3, -3, -2, -1]
SIDE = {1: "top", 2: "top", 3: "right", 4: "right", 5: "bottom", 6: "bottom", 7: "left", 8: "left"}


def tiles():
    """Tiles with switch matrices (all except the four corners)"""
    for r in LETTERS:
        for c in LETTERS:
            if r in "AI" and c in "AI":
                continue
            yield r + c


def positions(lines):
    """Name 'AB.8.1' -> G coordinate '172G32' as in the Magic entries"""
    pos = {}
    for t in tiles():
        row = lines.row_info["row.%s.local.1" % t[0]][0]
        col = lines.col_info["col.%s.local.1" % t[1]][0]
        for num in (1, 2):
            if t[0] == "I":
                x, y = (col, row - 2) if num == 1 else (col + 3, row + 1)
            else:
                x, y = (col, row + 1) if num == 1 else (col + 3, row - 2)
            pos["%s.8.%d" % (t, num)] = "%dG%d" % (x, y)
    return pos


def pin_g(g, pin):
    """G coordinate (x, y) of pin 1-8 of the matrix at g"""
    x, y = (int(v) for v in g.split("G"))
    return x + DX[pin - 1], y + DY[pin - 1]


def connections(entries, lines):
    """Name -> {(p1, p2): bit number} with p1 < p2; error if a Magic bit belongs to no matrix"""
    by_g = {g: name for name, g in positions(lines).items()}
    conn = collections.defaultdict(dict)
    for e in entries:
        if e.kind != "switch":
            continue
        g, p1, p2 = e.key
        if g not in by_g:
            raise ValueError("Magic bit %d at %s belongs to no switch matrix" % (e.index, g))
        conn[by_g[g]][tuple(sorted((p1, p2)))] = e.index
    return dict(conn)


def patterns(conn):
    """Pattern (sorted pin pairs) -> list of the matrices with exactly this pattern"""
    by_pattern = collections.defaultdict(list)
    for name, pairs in conn.items():
        by_pattern[tuple(sorted(pairs))].append(name)
    return dict(by_pattern)
