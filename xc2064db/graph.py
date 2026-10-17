"""Routing-Graph des XC2064 aus den Daten (Stand Stufe 3: CLB-Feld mit seinen Kanälen und die IOBs).

Knoten sind elektrisch zusammenhängende Leitungsstücke, Verbindungen sind die programmierbaren Punkte der
Bitkarte (PIP-Bits, Magic-Bits der Switch-Matrizen, Codes der CLB- und IOB-Muxe) und feste Verdrahtung.

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
    (col.C.local.6 an b). Am Rand sind diese Quellen Pads: der Eingang "Pnn.I" des Pads (iob.js).
  - IOBs (iob.js): Knoten "Pnn.O" (Ausgangs-Mux zum Pad), "Pnn.T" (Tristate-Mux) und "Pnn.I" (Eingang vom
    Pad). Die Pin-Leitungen an den Kreuzungen (io1-io6, x, clbl/clbr/clbw, local.0 und local.5 am Rand)
    gehören zum IOB und sind keine eigenen Knoten.

Verbindungsarten (Conn.kind): pip (PIP-Bit, zwischen allgemeinen Leitungen in beide Richtungen),
out (PIP-Bit von X/Y auf eine Leitung), switch (Magic-Bit), junction (Verbindungspunkt der fünften
Leitung), mux (CLB-Eingang: Quelle -> Pin, bits = Mux-Bits, code), iobo/iobt (Ausgangs- bzw. T-Mux eines
IOB: Quelle -> Pnn.O/T, mit code; Treiber aus/an sind Codes ohne Quelle), iobi (PIP-Bit: Pnn.I ->
Leitung), clkbuf (Eingang eines Taktpuffers, Code unbekannt), bidi (Repowering-Puffer, nur im Prüfmodus
split_bidi). Die Einträge aus iob.js ohne PIP-Bit stehen in Graph.unmodelled. Konstanten gibt es im
Original nicht als Leitung (nextpnr: pack() faltet sie in LUT-Inhalte).
"""
import bisect
import collections
import re

from . import bitmap, clbmux, iobmux, switches
from .lines import Lines

LETTERS = "ABCDEFGHI"
Conn = collections.namedtuple("Conn", "kind a b bits code name")
Buffer = collections.namedtuple("Buffer", "name line g bit seg")
CODED = ("mux", "iobo", "iobt", "clkbuf", "bidi")  # Verbindungen über einen Code statt eines PIP-Bits


def conn_on(cn, raw):
    """Ist die Verbindung im Bitstream raw (0 = programmiert) geschaltet? Code None (unbekannt): nie."""
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
        """split_bidi: Einzelsegmente an den Repowering-Puffern auftrennen (Stück dahinter: Zusatz "+", Puffer
        als zwei gerichtete Verbindungen "bidi" mit dem Bitwert als Code). Nur für Prüfungen: Ein Puffer ist
        nie aus, beide Stücke führen also immer dasselbe Netz; für den Router bleibt das Segment ein Knoten,
        die Richtung folgt aus dem Routing (bidi_bit)."""
        self.entries = entries or bitmap.load()
        self.lines = lines or Lines()
        self.split_bidi = split_bidi
        self.conns = []
        self.unmodelled = []  # (Pin, Eintrag aus iob.js, Grund)
        self._cuts()
        self._bidi()
        self._pips()
        self._switches()
        self._iobs()
        self._muxes()
        self._clkbufs()
        used = {b for cn in self.conns for b in cn.bits}
        self.skipped = collections.Counter(
            "PIP %s" % self.lines.pip_name(e.key[0]) for e in self.entries if e.kind == "pip" and e.index not in used)

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

    def _bidi(self):
        """Repowering-Puffer an den Grenzen der 9 Sektionen (Datenblatt): je Bidi-Bit ein Puffer auf einem
        Einzelsegment, senkrecht über den Zeilen D und G (alle local.1-5), waagerecht vor den Spalten D und G.
        Bit 0 (programmiert): der Puffer treibt nach unten bzw. rechts, Bit 1: nach oben bzw. links (belegt
        mit TEST1.RBT und AND_OR.BIT, siehe bidi_check). buffers: Liste Buffer(Name, Leitung, Lage G entlang
        der Leitung, Bit, Segment)."""
        self.buffers = []
        self.bidi_at = collections.defaultdict(list)
        for e in self.entries:
            if e.kind != "bidi":
                continue
            gx, gy = (int(v) for v in e.key[0].split("G"))
            col, row = self.lines.col_name.get(gx), self.lines.row_name.get(gy)
            if (col is None) == (row is None):
                raise ValueError("Bidi %s liegt nicht auf genau einer Leitung" % e.key[0])
            line, g = (col, gy) if col else (row, gx)
            seg = self._seg_base(line, g, line.startswith("col."))
            self.buffers.append(Buffer(e.key[0], line, g, e.index, seg))
            self.bidi_at[line].append((g, e.index, e.key[0]))
        if self.split_bidi:
            for b in self.buffers:
                self.conns.append(Conn("bidi", b.seg, b.seg + "+", [b.bit], 0, "%s %s" % (b.name, b.line)))
                self.conns.append(Conn("bidi", b.seg + "+", b.seg, [b.bit], 1, "%s %s" % (b.name, b.line)))

    def bidi_bit(self, buf, g_in):
        """Bitwert des Puffers buf, wenn das Signal bei g_in (G entlang der Leitung) in sein Segment kommt"""
        before = g_in > buf.g if buf.line.startswith("col.") else g_in < buf.g
        return 0 if before else 1

    def _beyond(self, line, base, g):
        """Knoten an der Stelle g des Stücks base: base selbst oder, im Prüfmodus split_bidi hinter einem
        Puffer des Stücks (unterhalb bzw. rechts davon), base + "+" """
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
        """Knoten der senkrechten Leitung line an der Höhe y (G)"""
        return self._beyond(line, self._seg_col(line, y), y)

    def seg_row(self, line, x):
        """Knoten der waagerechten Leitung line an der Stelle x (G)"""
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
                raise ValueError("%s: Kreuzung bei G %d liegt in einer Switch-Matrix" % (line, y))
        r = cuts[i - 1][1] if i > 0 else _prev(cuts[0][1])
        if r < "A" or r > "H":
            raise ValueError("%s: Kreuzung bei G %d außerhalb der Segmente" % (line, y))
        return "%s@%s" % (line, r)

    def _seg_row(self, line, x):
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

    @staticmethod
    def _out_pip(c, ck, r, rk):
        """X der CLBs in Spalte H kreuzt den Randkanal auf Höhe der Zeile b (col.I.* x row.R.b)"""
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
                continue  # Eingangs-Pip eines IOB (_iobs) oder nicht erfasst
            name = "%s:%s" % (col, row)
            if rk in ("io6", "y", "b"):  # CLB-Ausgang X (Spalte I: auf Höhe b) bzw. Y der CLB links der Spalte
                clb = r + _prev(c)
                src = "%s.%s" % (clb, "Y" if rk == "y" else "X")
                self.conns.append(Conn("out", src, self.seg_col(col, gy), [e.index], None, name))
            elif rk == "local.0":  # Verbindungspunkt der fünften Leitung (über D und G hinter dem Puffer)
                self.conns.append(Conn("junction", self.seg_col("col.%s.local.5" % c, gy),
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
        px, py = switches.pin_g(self.sm_g[sm], pin)
        if side == "top":
            return self._beyond(line, "%s@%s" % (line, _prev(t[0])), py)
        if side == "bottom":
            return "%s@%s" % (line, t[0])
        if side == "left":
            return self._beyond(line, "%s@%s" % (line, _prev(t[1])), px)
        return "%s@%s" % (line, t[1])

    def _iobs(self):
        """IOBs (iob.js): O- und T-Mux mit Codes, Eingangs-Pips; Pad -> CLB-Pin merkt sich pad_of_clb"""
        self.iobs = iobmux.iobs(self.lines, self.entries)
        pip_bit = {e.key[0]: e.index for e in self.entries if e.kind == "pip"}
        self.pad_of_clb = {}  # (CLB-Pin, Seite T/L/B) -> Pin des Pads
        for pin, iob in sorted(self.iobs.items()):
            for which, lst, codes, bits in (("O", iob.o, iob.omux, iob.obits), ("T", iob.t, iob.tmux, iob.tbits)):
                bitl = [bits[n] for n in sorted(bits)]
                for code, k in sorted(codes.items()):
                    ent = lst[k]
                    src = self.iob_source(ent)
                    if src is None:
                        self.unmodelled.append((pin, ent.spec, "Quelle des %s-Mux" % which))
                        continue
                    self.conns.append(Conn("iob" + which.lower(), src, "%s.%s" % (pin, which), bitl, code,
                                           "%s.%s %s" % (pin, which, ent.spec)))
            for ent in iob.i:
                if ent.kind == "clb":
                    self.pad_of_clb[(ent.special, iob.style[0].upper())] = pin
                    continue
                bit = pip_bit.get(ent.g)
                if ent.kind != "route" or not self._route_ok(ent) or bit is None:
                    self.unmodelled.append((pin, ent.spec, "Eingang (%s)" % (ent.kind if bit else "kein PIP-Bit")))
                    continue
                self.conns.append(Conn("iobi", "%s.I" % pin, self.route_node(ent), [bit], None,
                                       "%s:%s" % (ent.col, ent.row)))

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
                if src.startswith("pad:"):  # Pad am Rand: dessen Eingang (iob.js)
                    pin = self.pad_of_clb.get((sink, src[4]))
                    if pin is None:
                        self.unmodelled.append((sink, s.name, "kein Pad"))
                        continue
                    src = pin + ".I"
                self.conns.append(Conn("mux", src, sink, bits, code, "%s %s" % (sink, s.line)))

    def _clkbufs(self):
        """Taktpuffer (Datenblatt Bild 8b): GCLK oben links treibt CLK.AA.O und col.*.clk, ACLK unten rechts
        row.I.clk. Ihre Eingangs-Muxe CLK.AA.I (6 Bits) und CLK.II.I (8 Bits) dekodiert auch Shirriff nicht, und
        kein XACT-Bitstream benutzt sie. Modelliert ist nur der Weg vom eigenen Pad (P9 bzw. P43) mit den
        Bits des Muxes und unbekanntem Code (None)."""
        bits = collections.defaultdict(dict)
        for e in self.entries:
            if e.kind == "clkmux":
                bits[e.key[0]][e.key[1]] = e.index
        for mux, pin, net in (("CLK.AA.I", "P9", "GCLK"), ("CLK.II.I", "P43", "ACLK")):
            self.conns.append(Conn("clkbuf", pin + ".I", net, [bits[mux][n] for n in sorted(bits[mux])], None,
                                   "%s %s" % (mux, pin)))

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

    # --- Prüfung der Puffer-Richtung -----------------------------------------------------------
    def bidi_check(self, raw):
        """Richtung der Repowering-Puffer in einem Bitstream (nur im Prüfmodus split_bidi). Je Puffer: ohne ihn
        die beiden Seiten des Netzes; liegt der Treiber (X/Y, Pnn.I) auf einer Seite und eine Senke
        (CLB-Eingang, Pnn.O/T) auf der anderen, muss das Bit dem Code dieser Richtung entsprechen.
        Ergebnis: Zähler passend, Liste der Widersprüche (Name, Bit, Richtung)."""
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

        def is_sink(n):
            return re.fullmatch(r"[A-H][A-H]\.[ABCDK]|P\d+\.[OT]", n)

        ok, bad = 0, []
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
                continue  # Ring über einen anderen Weg (kommt in den Bitstreams nicht vor)
            sides = [[n for n in parent if find(n) == find(x)] for x in (down.a, down.b)]
            drv = [any(is_driver(n) for n in s) for s in sides]
            snk = [any(is_sink(n) for n in s) for s in sides]
            if drv[0] and snk[1] and not drv[1]:
                code = down.code
            elif drv[1] and snk[0] and not drv[0]:
                code = up.code
            else:
                continue  # eine Seite unbenutzt: Richtung beliebig
            if raw[down.bits[0]] == code:
                ok += 1
            else:
                bad.append((name, raw[down.bits[0]], "nach unten/rechts" if code == down.code else "nach oben/links"))
        return ok, bad

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
