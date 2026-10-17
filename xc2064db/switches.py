"""Switch-Matrizen: je Kachel-Kreuzung zwei (XY.8.1 und XY.8.2), an den vier Ecken des Chips keine.
Jede hat 8 Pins, 1-2 oben, 3-4 rechts, 5-6 unten, 7-8 links (draw.js, Switch.pinCoord). Jede mögliche
Verbindung zweier Pins ist ein Magic-Bit der Bitkarte.

Die Lage (G-Koordinate, unter der die Magic-Bits stehen): Matrix 1 an local.1 der Spalte, Matrix 2 drei
Spalten weiter (local.3); in Zeile I gespiegelt. Für Zeile I gilt XACTs Benennung (TEST1.LCA: IB.8.2.0 liegt
bei 30G11) wie in Shirriffs getSwitchCoords(); seine Switch-Klasse vertauscht dort 8.1 und 8.2.

Pins: Pin n (1-8) hier und in den Magic-Bits ist Pin n-1 bei XACT (TEST1.LCA: AB.8.1.6/AB.8.1.4 ist das
Magic-Bit "AB.8.1 5 7"). Pin p (0-7 bei XACT) liegt bei gPt + (DX[p], DY[p]) in G-Koordinaten.
"""
import collections

LETTERS = "ABCDEFGHI"
DX = [0, 1, 2, 2, 1, 0, -1, -1]
DY = [0, 0, -1, -2, -3, -3, -2, -1]
SIDE = {1: "top", 2: "top", 3: "right", 4: "right", 5: "bottom", 6: "bottom", 7: "left", 8: "left"}


def tiles():
    """Kacheln mit Switch-Matrizen (alle außer den vier Ecken)"""
    for r in LETTERS:
        for c in LETTERS:
            if r in "AI" and c in "AI":
                continue
            yield r + c


def positions(lines):
    """Name 'AB.8.1' -> G-Koordinate '172G32' wie in den Magic-Einträgen"""
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
    """G-Koordinate (x, y) von Pin 1-8 der Matrix an g"""
    x, y = (int(v) for v in g.split("G"))
    return x + DX[pin - 1], y + DY[pin - 1]


def connections(entries, lines):
    """Name -> {(p1, p2): Bitnummer} mit p1 < p2; Fehler, wenn ein Magic-Bit zu keiner Matrix gehört"""
    by_g = {g: name for name, g in positions(lines).items()}
    conn = collections.defaultdict(dict)
    for e in entries:
        if e.kind != "switch":
            continue
        g, p1, p2 = e.key
        if g not in by_g:
            raise ValueError("Magic-Bit %d bei %s gehört zu keiner Switch-Matrix" % (e.index, g))
        conn[by_g[g]][tuple(sorted((p1, p2)))] = e.index
    return dict(conn)


def patterns(conn):
    """Muster (sortierte Pin-Paare) -> Liste der Matrizen mit genau diesem Muster"""
    by_pattern = collections.defaultdict(list)
    for name, pairs in conn.items():
        by_pattern[tuple(sorted(pairs))].append(name)
    return dict(by_pattern)
