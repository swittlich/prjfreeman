"""Routing-Graph des XC2064 aus den Daten (Stand Stufe 2: das CLB-Feld mit seinen Kanälen).

Knoten sind elektrisch zusammenhängende Leitungsstücke, Verbindungen sind die programmierbaren Punkte der
Bitkarte (PIP-Bits, Magic-Bits der Switch-Matrizen, Codes der CLB-Eingangs-Muxe) und feste Verdrahtung.

Segmente (Datenblatt "General-Purpose Interconnect", Bild 7b; Lage aus den G-Koordinaten):
  - Die Einzelsegmente local.1-4 senkrecht und die waagerechten der Switch-Matrizen enden an den Matrizen.
    Ein Pin liegt bei gPt + (DX, DY) (switches); die Matrix trennt die senkrechten Leitungen ihrer oberen und
    unteren Pins zwischen deren Höhen, die waagerechten zwischen den linken und rechten Pins.
    Knoten: "col.C.local.k@R" (Spalte C, Stück unterhalb der Matrix in Zeile R) und "row.R.local.k@C".
  - Die fünfte senkrechte Leitung (local.5) hat keine Matrix. Ihr Stück der Zeile R beginnt am
    Verbindungspunkt "col.C.local.5:row.R.local.0", läuft im Kanal R auf der Spur von local.6 (Kreuzungen mit
    local.3/4), dann auf der Spur von local.5 an der CLB-Zeile R vorbei (B, C, Y) bis in den Kanal R+1 hinein
    (Kreuzungen mit dessen local.0, local.3, local.4). Der Verbindungspunkt der Zeile R verbindet das Stück
    R-1 mit dem Stück R. In Zeile A gibt es kein Stück darüber, die Kreuzungen in Zeile I gehören zu Stück H.
    Knoten "col.C.local.5@R". Belegt durch TEST1.LCA (Netz p1).
  - Long Lines laufen über die ganze Höhe bzw. Breite: Knoten = Leitungsname.
  - GCLK (col.*.clk, CLK.AA.O) ist ein Knoten "GCLK", die ACLK-Leitung unten (row.I.clk) ein Knoten "ACLK".
  - CLB-Ausgänge: X (Zeile io6) und Y (Zeile y) einer CLB "RC.X", "RC.Y", Eingänge "RC.A" ... "RC.K".
  - Direktverbindungen (Datenblatt "Direct Interconnect"): X geht fest auf A/B der CLB darunter (Quellen
    row.R.io4, col.C.x an b) und C/D der CLB darüber (col.C.x an c, row.R+1.io3), Y auf B der CLB rechts
    (col.C.local.6 an b). Am Rand sind diese Quellen Pads (Stufe 3), hier als "pad:T|L|B" markiert.

Verbindungsarten (Conn.kind): pip (PIP-Bit, zwischen allgemeinen Leitungen in beide Richtungen),
out (PIP-Bit von X/Y auf eine Leitung), switch (Magic-Bit), junction (Verbindungspunkt der fünften
Leitung), mux (CLB-Eingang: Quelle -> Pin, bits = Mux-Bits, code). Nicht erfasst (Stufe 3/4): IOB-Leitungen,
die fünften Leitungen und local.0 am Rand, die Taktpuffer.
"""
import bisect
import collections
import re

from . import bitmap, clbmux, switches
from .lines import Lines

LETTERS = "ABCDEFGHI"
Conn = collections.namedtuple("Conn", "kind a b bits code name")


def _split(name):
    m = re.fullmatch(r"(col|row)\.([A-I])\.(.+)", name)
    return (m[1], m[2], m[3]) if m else (None, None, name)


def _prev(c):
    return chr(ord(c) - 1)


def _next(c):
    return chr(ord(c) + 1)


class Graph:
    def __init__(self, entries=None, lines=None):
        self.entries = entries or bitmap.load()
        self.lines = lines or Lines()
        self.conns = []
        self.skipped = collections.Counter()  # nicht erfasste PIP-Bits nach Grund
        self._cuts()
        self._pips()
        self._switches()
        self._muxes()

    # --- Segmente ------------------------------------------------------------------------------
    def _cuts(self):
        """Trennstellen je Leitung: Liste (Mitte, Buchstabe der Matrix) entlang der Leitung"""
        ln = self.lines
        self.sm_g = switches.positions(ln)
        col_cuts, row_cuts = collections.defaultdict(list), collections.defaultdict(list)
        self.sm_pins = {}  # (Matrix, Pin) -> (Leitung, Seite)
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
        # senkrecht: von oben (großes G) nach unten; waagerecht: von links nach rechts
        self.col_cuts = {k: sorted(v, key=lambda c: -c[0]) for k, v in col_cuts.items()}
        self.row_cuts = {k: sorted(v) for k, v in row_cuts.items()}

    def seg_col(self, line, y):
        """Knoten der senkrechten Leitung line an der Höhe y (G)"""
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
                raise ValueError("%s: Kreuzung bei G %d liegt in einer Switch-Matrix" % (line, y))
        r = cuts[i - 1][1] if i > 0 else _prev(cuts[0][1])
        if r < "A" or r > "H":
            raise ValueError("%s: Kreuzung bei G %d außerhalb der Segmente" % (line, y))
        return "%s@%s" % (line, r)

    def seg_row(self, line, x):
        cuts = self.row_cuts.get(line)
        if not cuts:
            return {"row.I.clk": "ACLK", "CLK.AA.O": "GCLK"}.get(line, line)
        xs = [cx for cx, _ in cuts]
        for cx, _ in cuts:
            if abs(cx - x) < 1.5:
                raise ValueError("%s: Kreuzung bei G %d liegt in einer Switch-Matrix" % (line, x))
        i = bisect.bisect_left(xs, x)
        c = cuts[i - 1][1] if i > 0 else _prev(cuts[0][1])
        if c < "A" or c > "H":
            raise ValueError("%s: Kreuzung bei G %d außerhalb der Segmente" % (line, x))
        return "%s@%s" % (line, c)

    def row_of_y(self, y):
        """Zeile (A-I), zu deren Block die Höhe y gehört (Block R: von io1 der Zeile R bis y der Zeile R)"""
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

    # --- Verbindungen --------------------------------------------------------------------------
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
            if not (self._general_col(c, ck) and self._general_row(r, rk)):
                self.skipped["IOB- oder Randleitung (Stufe 3)"] += 1
                continue
            name = "%s:%s" % (col, row)
            if rk in ("io6", "y"):  # CLB-Ausgang X bzw. Y der CLB links der Spalte
                clb = r + _prev(c)
                src = "%s.%s" % (clb, "X" if rk == "io6" else "Y")
                self.conns.append(Conn("out", src, self.seg_col(col, gy), [e.index], None, name))
            elif rk == "local.0":  # Verbindungspunkt der fünften Leitung
                self.conns.append(Conn("junction", "col.%s.local.5@%s" % (c, _prev(r)),
                                       "col.%s.local.5@%s" % (c, r), [e.index], None, name))
            else:
                self.conns.append(Conn("pip", self.seg_col(col, gy), self.seg_row(row, gx), [e.index], None, name))

    def _switches(self):
        conn = switches.connections(self.entries, self.lines)
        for sm, pairs in sorted(conn.items()):
            for (p1, p2), bit in sorted(pairs.items()):
                a, b = self.sm_node(sm, p1), self.sm_node(sm, p2)
                self.conns.append(Conn("switch", a, b, [bit], None, "%s %d-%d" % (sm, p1, p2)))

    def sm_node(self, sm, pin):
        """Knoten am Pin einer Switch-Matrix"""
        line, side = self.sm_pins[(sm, pin)]
        t = sm[:2]
        if side == "top":
            return "%s@%s" % (line, _prev(t[0]))
        if side == "bottom":
            return "%s@%s" % (line, t[0])
        if side == "left":
            return "%s@%s" % (line, _prev(t[1]))
        return "%s@%s" % (line, t[1])

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
                self.conns.append(Conn("mux", src, sink, bits, code, "%s %s" % (sink, s.line)))

    def mux_source(self, m, s, gx, gy):
        r, c = m.tile
        _, _, kind = _split(s.line)
        if kind == "local.6":  # Y der CLB links -> B
            return "%s%s.Y" % (r, _prev(c))
        if kind == "x":  # X der CLB darüber -> B, X der CLB darunter -> C
            if m.pin == "B":
                return "pad:T" if r == "A" else "%s%s.X" % (_prev(r), c)
            return "pad:B" if r == "H" else "%s%s.X" % (_next(r), c)
        if kind == "io4":
            return "%s%s.X" % (_prev(r), c)
        if kind == "io3" and m.pin == "D":
            return "%s%s.X" % (_next(r), c)
        if kind == "io3":  # Spalte A, B: Pad links
            return "pad:L"
        if kind == "io2":  # A oben bzw. D unten: Pad
            return "pad:T" if m.pin == "A" else "pad:B"
        if kind == "clk":
            return "GCLK"
        if s.line.startswith("col."):
            return self.seg_col(s.line, gy)
        return self.seg_row(s.line, gx)

    # --- Abfragen ------------------------------------------------------------------------------
    def nodes(self):
        n = set()
        for cn in self.conns:
            n.add(cn.a)
            n.add(cn.b)
        return n

    def by_bit(self):
        """Bitnummer -> Liste der Verbindungen, die dieses Bit benutzen"""
        d = collections.defaultdict(list)
        for cn in self.conns:
            for b in cn.bits:
                d[b].append(cn)
        return d
