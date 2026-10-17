# Chip-Datenbank für ein Modell des Xilinx XC2064 (1985, das erste FPGA) als Himbächel-uarch.
#
# Grundlagen: XC2000-Datenblatt; Ken Shirriffs Reverse Engineering (github.com/shirriff/xc2064, als
# Submodule shirriff-xc2064) mit der Bitkarte XC2064-def.txt, den Leitungsnamen (draw.js) und den
# CLB-Eingangs-Muxen (clb.js). Das Paket xc2064db (arch/xc2064/xc2064db) liest diese Daten; der
# Routing-Graph des CLB-Felds entsteht aus xc2064db.graph, jeder Pip dort entspricht einem Bit bzw. einem
# Mux-Code des Originals. Die IOBs hängen noch vereinfacht am Randkanal (Stufe 3, siehe README).
#
# Raster (x, y; y nach unten): 8x8 CLBs bei x, y = 1..8 und ein IO-Ring bei 0 bzw. 9. Shirriffs 9x9
# Kacheln AA..II (Zeile, Spalte) entsprechen x = Spalte, y = Zeile = 1..9: jede enthält die Kanäle
# oberhalb und links ihrer CLB und an deren Kreuzung zwei Switch-Matrizen (8.1, 8.2). Die 9. Spalte/Zeile
# (I) enthält nur Routing und Pads, die Kacheln x = 0 und y = 0 die Pads links und oben.
#
#   CLB (laut Decoder):
#     Eingänge A, B, C, D, Takt K; Ausgänge X, Y
#     F, G  : je eine Funktion von 3 Variablen; Eingang 1 aus {A, B}, 2 aus {B, C}, 3 aus {C, D, Q}
#     FG    : F und G gemeinsam als eine Funktion von 4 Variablen, B wählt zwischen ihnen
#     FF    : Flipflop oder Latch; Daten aus F (bzw. FG); Takt aus K, C oder G (invertierbar);
#             asynchrones Set aus A oder F, asynchrones Reset aus D oder G
#     X, Y  : je aus Q, F oder G
#   Routing (xc2064db.graph):
#     Kanäle:         senkrecht local.1-4 (durch die Matrizen), die fünfte Leitung (local.5, versetzt mit
#                     Verbindungspunkt je Zeile), 2 Long Lines und GCLK; waagerecht 4 Einzelsegmente und
#                     eine Long Line, am Rand 4 Einzelsegmente und 2 Long Lines
#     Switch-Matrix:  2 je Kreuzung, 8 Pins, Verbindungen aus den Magic-Bits (innen 20, am Rand 10)
#     CLB-Eingänge:   alle Quellen aus clb.js (A 6-7, B 10, C 8, D 6-7, K 2)
#     Ausgänge:       X (Zeile io6) und Y (Zeile y) über ihre PIP-Bits in den Kanal rechts, X fest an A/B
#                     der CLB darunter und C/D der CLB darüber, Y fest an B der CLB rechts
#     Takt:           GCLK (col.*.clk) auf B und K, ACLK (row.I.clk) über die senkrechten long.2 auf K
#   Übergangsweise (Stufe 3/4): IOBs am Randkanal parallel zum Rand (4 Einzelsegmente, 2 Long Lines),
#   Direktverbindungen zu den Pads wie bisher, Taktpuffer fest an P9 (GCLK) und P43 (ACLK), Konstanten.
from os import path
import re
import sys
sys.path.append(path.join(path.dirname(__file__), "../.."))
from himbaechel_dbgen.chip import *

ARCH_DIR = path.dirname(path.dirname(path.realpath(__file__)))
sys.path.insert(0, ARCH_DIR)
from xc2064db.graph import Graph  # noqa: E402

N_CLB = 8
X = N_CLB + 2
Y = N_CLB + 2
LAST = N_CLB + 1           # Index der 9. Switch-Matrix-Spalte/-Zeile
TRACKS = [(m, k) for m in range(2) for k in range(2)]  # IOB-Zugänge: local.1-4 des Randkanalstücks
LETTERS = "ABCDEFGHI"
GCLK_PIN, ACLK_PIN = "P9", "P43"

# Pads nach Shirriffs iob.js: (Pin, Kachel Zeile+Spalte, Anschlussrichtung)
PADS = [
    ("P9", "AA", "topleft"), ("P8", "AB", "topright"), ("P7", "AB", "topleft"), ("P6", "AC", "topright"),
    ("P5", "AC", "topleft"), ("P4", "AD", "topright"), ("P3", "AD", "topleft"), ("P2", "AE", "topright"),
    ("P68", "AE", "topleft"), ("P67", "AF", "topright"), ("P66", "AF", "topleft"), ("P65", "AG", "topright"),
    ("P64", "AG", "topleft"), ("P63", "AH", "topright"), ("P62", "AH", "topleft"), ("P61", "AI", "topright"),
    ("P59", "BI", "rightlower"), ("P58", "BI", "rightupper"), ("P57", "CI", "rightlower"),
    ("P56", "CI", "rightupper"), ("P55", "DI", "rightlower"), ("P54", "DI", "rightupper"),
    ("P53", "EI", "rightlower"), ("P51", "FI", "rightlower"), ("P50", "FI", "rightupper"),
    ("P49", "GI", "rightlower"), ("P48", "GI", "rightupper"), ("P47", "HI", "rightlower"),
    ("P46", "HI", "rightupper"),
    ("P43", "II", "bottomright"), ("P42", "IH", "bottomleft"), ("P41", "IH", "bottomright"),
    ("P40", "IG", "bottomleft"), ("P39", "IG", "bottomright"), ("P38", "IF", "bottomleft"),
    ("P37", "IF", "bottomright"), ("P36", "IE", "bottomleft"), ("P34", "IE", "bottomright"),
    ("P33", "ID", "bottomleft"), ("P32", "ID", "bottomright"), ("P31", "IC", "bottomleft"),
    ("P30", "IC", "bottomright"), ("P29", "IB", "bottomleft"), ("P28", "IB", "bottomright"),
    ("P27", "IA", "bottomleft"),
    ("P24", "HA", "leftupper"), ("P23", "HA", "leftlower"), ("P22", "GA", "leftupper"),
    ("P21", "GA", "leftlower"), ("P20", "FA", "leftupper"), ("P19", "FA", "leftlower"),
    ("P17", "EA", "leftlower"), ("P16", "DA", "leftupper"), ("P15", "DA", "leftlower"),
    ("P14", "CA", "leftupper"), ("P13", "CA", "leftlower"), ("P12", "BA", "leftupper"),
    ("P11", "BA", "leftlower"),
]


def pad_info(pin, tile, style):
    """Kachel (x, y), z, Seite und das Kanalstück (Seite, Index) eines Pads im Modellraster."""
    r, c = LETTERS.index(tile[0]) + 1, LETTERS.index(tile[1]) + 1
    second = style in ("topright", "bottomright", "rightlower", "leftlower")
    z = 1 if second else 0
    if style.startswith("top"):
        side, x, y, idx = "T", c, 0, c
    elif style.startswith("bottom"):
        side, x, y, idx = "B", c, LAST, c
    elif style.startswith("right"):
        side, x, y, idx = "R", LAST, r, r
    else:
        side, x, y, idx = "L", 0, r, r
    # Kanalstück parallel zum Rand: das zweite Pad einer Kachel ("topright", "rightlower", ...) hängt
    # am Stück der vorherigen CLB (Shirriffs iob.js: clbw-Spalten bzw. Zeilen der vorherigen Reihe)
    seg = idx - 1 if second else idx
    return dict(pin=pin, x=x, y=y, z=z, side=side, seg=seg)


PAD_INFO = [pad_info(*p) for p in PADS]

# Direktverbindungen zwischen Rand-CLB und IOB (übergangsweise wie bisher): (Seite, z, Richtung, Draht).
# "in": Eingang vom Pad -> CLB-Pins (Quelle pad:L/T/B im Graphen), "out": X der CLB -> Ausgang zum Pad.
PAD_DIRECT = [
    ("L", 1, "in", "PL"),     # leftlower -> B
    ("T", 0, "in", "PT"),     # topleft -> A, B
    ("B", 0, "in", "PB"),     # bottomleft -> C, D
    ("T", 1, "out", "IO1_X"), # X -> topright
    ("B", 1, "out", "IO1_X"), # X -> bottomright
    ("R", 0, "out", "IO0_X"), # X (und Y) -> rightupper
]


def is_clb(x, y):
    return 1 <= x <= N_CLB and 1 <= y <= N_CLB


def has_sm(x, y):
    return 1 <= x <= LAST and 1 <= y <= LAST


def is_io(x, y):
    return not is_clb(x, y) and (has_sm(x, y) or any(p["x"] == x and p["y"] == y for p in PAD_INFO)
                                 or (x == 0 and 1 <= y <= N_CLB) or (y == 0 and 1 <= x <= LAST))


def edge_pad(side, z, seg):
    """Pad z am Randkanalstück (side, seg), falls es das Pad gibt."""
    return next((p for p in PAD_INFO if p["side"] == side and p["z"] == z and p["seg"] == seg), None)


def edge_clb(side, seg):
    """Rand-CLB neben dem Randkanalstück (side, seg)."""
    return {"L": (1, seg), "R": (N_CLB, seg), "T": (seg, 1), "B": (seg, N_CLB)}[side]


def tile_xy(t):
    """Kachel 'BC' (Zeile B, Spalte C) -> (x, y)"""
    return LETTERS.index(t[1]) + 1, LETTERS.index(t[0]) + 1


def tile_name(x, y):
    return LETTERS[y - 1] + LETTERS[x - 1]


# --- Drahtnamen ---------------------------------------------------------------------------------
REL = {(0, 0): "", (1, 0): "_R", (-1, 0): "_L", (0, -1): "_U", (0, 1): "_D"}


def wire_name(node, t):
    """Name des Drahts von Graph-Knoten node in Kachel t. Senkrechte Leitungen V<k>, waagerechte H<k>,
    Long Lines VL<k>/HL<k>; Zusatz _U/_D/_L/_R für das Stück der Nachbarkachel (oben, unten, links,
    rechts). CLB-Pins heißen wie der Pin, X/Y der Nachbar-CLBs XT (X darüber), XB (X darunter), YL (Y links)."""
    if node in ("GCLK", "ACLK"):
        return node
    if node.startswith("pad:"):
        return {"pad:T": "PT", "pad:L": "PL", "pad:B": "PB"}[node]
    m = re.fullmatch(r"([A-H])([A-H])\.([ABCDKXY])", node)
    if m:
        d = (ord(m[2]) - ord(t[1]), ord(m[1]) - ord(t[0]))
        if d == (0, 0):
            return m[3]
        return {("X", 0, -1): "XT", ("X", 0, 1): "XB", ("Y", -1, 0): "YL"}[(m[3],) + d]
    m = re.fullmatch(r"(col|row)\.([A-I])\.(local|long)\.(\d)(?:@([A-I]))?", node)
    if not m:
        raise ValueError("unbekannter Knoten %s" % node)
    kind, letter, lk, k, seg = m.groups()
    prefix = ("V" if kind == "col" else "H") + ("L" if lk == "long" else "") + k
    if kind == "col":
        d = (ord(letter) - ord(t[1]), (ord(seg) - ord(t[0])) if seg else 0)
    else:
        d = ((ord(seg) - ord(t[1])) if seg else 0, ord(letter) - ord(t[0]))
    return prefix + REL[d]


def place(cn):
    """Kachel, in der der Pip einer Verbindung liegt"""
    if cn.kind == "mux":
        return cn.b[:2]
    if cn.kind == "out":
        return cn.a[:2]
    if cn.kind == "switch":
        return cn.name[:2]
    if cn.kind == "junction":
        return cn.b.split("@")[1] + cn.b.split(".")[1]
    col, row = cn.name.split(":")
    return row.split(".")[1] + col.split(".")[1]


def timing_class(cn):
    if cn.kind == "switch":
        return "SM"
    if cn.kind in ("mux", "out"):
        return "INMUX" if cn.kind == "mux" else "OUTDRV"
    if ".long." in cn.a or ".long." in cn.b or "CLK" in cn.a or "CLK" in cn.b:
        return "LONGDRV"
    return "PIP"


class Builder:
    def __init__(self, ch):
        self.ch = ch
        self.graph = Graph()
        self.wires = {}  # (x, y) -> {Name: Typ}
        self.pips = {}  # (x, y) -> {(src, dst): Klasse}
        self.node_wires = {}  # Knoten -> [(x, y, Name)]

    def wire(self, xy, name, typ):
        """Draht anlegen; ROUTING (aus dem Graphen) weicht einem genaueren Typ (CLB_IN, ...)"""
        old = self.wires.setdefault(xy, {}).get(name)
        if old not in (None, "ROUTING", typ) and typ != "ROUTING":
            raise ValueError("Draht %s in %s mit zwei Typen %s, %s" % (name, xy, old, typ))
        if old in (None, "ROUTING"):
            self.wires[xy][name] = typ

    def node(self, node, xy, name):
        lst = self.node_wires.setdefault(node, [])
        if (xy[0], xy[1], name) not in lst:
            lst.append((xy[0], xy[1], name))
        owner = self.wire_owner.setdefault((xy, name), node)
        if owner != node:
            raise ValueError("Draht %s in %s gehört zu %s und %s" % (name, xy, owner, node))

    def pip(self, xy, src, dst, cls):
        self.pips.setdefault(xy, {})[(src, dst)] = cls

    def routing(self):
        self.wire_owner = {}
        for cn in self.graph.conns:
            t = place(cn)
            xy = tile_xy(t)
            a, b = wire_name(cn.a, t), wire_name(cn.b, t)
            for n, w in ((cn.a, a), (cn.b, b)):
                self.wire(xy, w, "ROUTING")
                self.node(n, xy, w)
            cls = timing_class(cn)
            self.pip(xy, a, b, cls)
            if cn.kind in ("pip", "switch", "junction"):  # Pass-Transistor: beide Richtungen
                self.pip(xy, b, a, cls)

    def clb(self, x, y):
        """Bels und interne Pips einer CLB"""
        xy = (x, y)
        for w in ("GND", "VCC"):
            self.wire(xy, w, w)
        for p in "ABCDK":
            self.wire(xy, p, "CLB_IN")
            if p != "K":  # Konstanten auf A-D (übergangsweise, Stufe 4: in die LUT-Inhalte)
                self.pip(xy, "GND", p, "")
                self.pip(xy, "VCC", p, "")
        for o in "XY":
            self.wire(xy, o, "CLB_OUT")
        self.wire(xy, "Q", "FF_Q")
        lut_in = [("A", "B"), ("B", "C"), ("C", "D", "Q")]
        self.bels = getattr(self, "bels", {})
        bels = self.bels.setdefault(xy, [])
        for name, z, n in (("F", 0, 3), ("G", 1, 3), ("FG", 2, 4)):
            pins = []
            for i in range(n):
                w = "%s_I%d" % (name, i)
                self.wire(xy, w, "LUT_IN")
                pins.append(("I[%d]" % i, w, PinType.INPUT))
                for s in (lut_in[i] if i < 3 else ("B",)):  # FG: I[3] = B wählt zwischen F und G
                    self.pip(xy, s, w, "LOCAL")
            self.wire(xy, "%s_O" % name, "LUT_OUT")
            pins.append(("O", "%s_O" % name, PinType.OUTPUT))
            bels.append((name, "LUT%d" % n, z, pins))
        for w in ("FF_D", "FF_CLK", "FF_S", "FF_R"):
            self.wire(xy, w, "FF_IN")
        for s, d in (("F_O", "FF_D"), ("FG_O", "FF_D"),
                     ("K", "FF_CLK"), ("C", "FF_CLK"), ("G_O", "FF_CLK"), ("FG_O", "FF_CLK"),
                     ("A", "FF_S"), ("F_O", "FF_S"), ("FG_O", "FF_S"),
                     ("D", "FF_R"), ("G_O", "FF_R"), ("FG_O", "FF_R")):
            self.pip(xy, s, d, "LOCAL")
        bels.append(("FF", "DFF", 3, [("D", "FF_D", PinType.INPUT), ("CLK", "FF_CLK", PinType.INPUT),
                                     ("S", "FF_S", PinType.INPUT), ("R", "FF_R", PinType.INPUT),
                                     ("Q", "Q", PinType.OUTPUT)]))
        for o in "XY":
            for s in ("F_O", "G_O", "FG_O", "Q"):
                self.pip(xy, s, o, "LOCAL")

    def iob(self, p):
        """IOB-Pad, übergangsweise am Randkanalstück parallel zum Rand (Stufe 3: iob.js)"""
        xy, z, side = (p["x"], p["y"]), p["z"], p["side"]
        for w in ("GND", "VCC"):
            self.wire(xy, w, w)
        for sfx, typ in (("I", "IO_I"), ("T", "IO_T"), ("O", "IO_O"), ("PAD", "IO_PAD")):
            self.wire(xy, "IO%d_%s" % (z, sfx), typ)
        self.bels = getattr(self, "bels", {})
        self.bels.setdefault(xy, []).append((p["pin"], "IOB", z, [
            ("I", "IO%d_I" % z, PinType.INPUT), ("T", "IO%d_T" % z, PinType.INPUT),
            ("O", "IO%d_O" % z, PinType.OUTPUT), ("PAD", "IO%d_PAD" % z, PinType.INOUT)]))
        seg = LETTERS[p["seg"] - 1]
        line = {"T": "row.A.local.%d@" + seg, "B": "row.I.local.%d@" + seg,
                "L": "col.A.local.%d@" + seg, "R": "col.I.local.%d@" + seg}[side]
        longs = {"T": ["row.A.long.2", "row.A.long.3"], "B": ["row.I.long.1", "row.I.long.2"],
                 "L": ["col.A.long.2", "col.A.long.3"], "R": ["col.I.long.1", "col.I.long.2"]}[side]
        access = []
        for i, (m, k) in enumerate(TRACKS):
            w = "IO%d_T%d%d" % (z, m, k)
            self.wire(xy, w, "PAD_ACCESS")
            self.node(line % (i + 1), xy, w)
            access.append(w)
        for i, n in enumerate(longs):
            w = "IO%d_L%d" % (z, i)
            self.wire(xy, w, "PAD_ACCESS")
            self.node(n, xy, w)
            access.append(w)
        for c in access:
            self.pip(xy, c, "IO%d_I" % z, "INMUX")
            self.pip(xy, "IO%d_O" % z, c, "OUTDRV")
            self.pip(xy, c, "IO%d_T" % z, "INMUX")
        for c in ("GND", "VCC"):
            self.pip(xy, c, "IO%d_I" % z, "")
            self.pip(xy, c, "IO%d_T" % z, "")
        # Direktverbindungen: X (rechts auch Y) der Rand-CLB in den Ausgangsmultiplexer, Pad -> CLB
        for dside, dz, d, w in PAD_DIRECT:
            if (dside, dz) != (side, z):
                continue
            cx, cy = edge_clb(side, p["seg"])
            clb = tile_name(cx, cy)
            if d == "out":
                outs = ["X", "Y"] if side == "R" else ["X"]
                for o in outs:
                    self.wire(xy, "IO%d_%s" % (z, o), "DIRECT")
                    self.node("%s.%s" % (clb, o), xy, "IO%d_%s" % (z, o))
                    self.pip(xy, "IO%d_%s" % (z, o), "IO%d_I" % z, "INMUX")
            else:
                self.node("pad:%s@%s" % (side, clb), xy, "IO%d_O" % z)
        # Taktpuffer an den Pads P9 (GCLK) und P43 (ACLK), übergangsweise ohne die Puffer-Muxe
        if p["pin"] in (GCLK_PIN, ACLK_PIN):
            net = "GCLK" if p["pin"] == GCLK_PIN else "ACLK"
            self.wire(xy, net + "_SRC", "GCLK")
            self.node(net, xy, net + "_SRC")
            self.pip(xy, "IO%d_O" % z, net + "_SRC", "GCLK")

    def pad_direct_nodes(self):
        """pad:T/L/B im Graphen gehören je CLB zu ihrem Rand-Pad: Knoten je CLB umbenennen"""
        for node in [n for n in self.node_wires if n in ("pad:T", "pad:L", "pad:B")]:
            for x, y, w in self.node_wires.pop(node):
                self.node_wires.setdefault("%s@%s" % (node, tile_name(x, y)), []).append((x, y, w))

    def build(self):
        ch = self.ch
        self.routing()
        self.pad_direct_nodes()
        for x in range(X):
            for y in range(Y):
                if is_clb(x, y):
                    self.clb(x, y)
        for p in PAD_INFO:
            self.iob(p)
        for x in range(X):
            for y in range(Y):
                xy = (x, y)
                tt = ch.create_tile_type("T_X%dY%d" % (x, y))
                for name, typ in sorted(self.wires.get(xy, {}).items()):
                    if typ in ("GND", "VCC"):
                        tt.create_wire(name, typ, const_value=typ)
                    else:
                        tt.create_wire(name, typ)
                for name, typ, z, pins in self.bels.get(xy, []):
                    bel = tt.create_bel(name, typ, z=z)
                    for pin, w, d in pins:
                        tt.add_bel_pin(bel, pin, w, d)
                for (src, dst), cls in sorted(self.pips.get(xy, {}).items()):
                    tt.create_pip(src, dst, timing_class=cls)
                if has_sm(x, y) and not (x in (1, LAST) and y in (1, LAST)):  # zuerst: Index = Matrix 8.1/8.2
                    tt.create_group("SM0", "SWITCHBOX")
                    tt.create_group("SM1", "SWITCHBOX")
                if is_clb(x, y):
                    tt.create_group("CLB", "CLB_FRAME")  # nur für die GUI: Rahmen der CLB
                if not is_clb(x, y) and not is_io(x, y):  # Ecken: Treiber der Konstanten
                    for w in ("GND", "VCC"):
                        if w not in self.wires.get(xy, {}):
                            tt.create_wire(w, w, const_value=w)
                    gnd = tt.create_bel("GND_DRV", "GND_DRV", z=0)
                    tt.add_bel_pin(gnd, "GND", "GND", PinType.OUTPUT)
                    vcc = tt.create_bel("VCC_DRV", "VCC_DRV", z=1)
                    tt.add_bel_pin(vcc, "VCC", "VCC", PinType.OUTPUT)
                ch.set_tile_type(x, y, "T_X%dY%d" % (x, y))
        for node, wires in self.node_wires.items():
            if len(wires) > 1:
                ch.add_node([NodeWire(x, y, w) for x, y, w in wires])


def set_timings(ch: Chip):
    # Größenordnung XC2064-70 (1985): Logik ~15 ns, Pass-Transistoren einige ns (Werte in ps)
    speed = "DEFAULT"
    tmg = ch.set_speed_grades([speed])
    for name, delay in (("SM", 2500), ("PIP", 1500), ("INMUX", 1500), ("LOCAL", 500), ("OUTDRV", 1500),
                        ("LONGDRV", 4000), ("GCLK", 3000)):
        tmg.set_pip_class(grade=speed, name=name, delay=TimingValue(delay),
                          in_cap=TimingValue(5000), out_res=TimingValue(1000))
    lut3 = ch.timing.add_cell_variant(speed, "XC2000_LUT3")
    for i in range(3):
        lut3.add_comb_arc(f"I[{i}]", "O", TimingValue(15000))
    lut4 = ch.timing.add_cell_variant(speed, "XC2000_LUT4")
    for i in range(4):
        lut4.add_comb_arc(f"I[{i}]", "O", TimingValue(18000))
    dff = ch.timing.add_cell_variant(speed, "XC2000_DFF")
    dff.add_setup_hold("CLK", "D", ClockEdge.RISING, TimingValue(8000), TimingValue(2000))
    dff.add_clock_out("CLK", "Q", ClockEdge.RISING, TimingValue(10000))


def main():
    ch = Chip("xc2064", "XC2064", X, Y)
    ch.strs.read_constids(path.join(path.dirname(__file__), "constids.inc"))
    ch.read_gfxids(path.join(path.dirname(__file__), "gfxids.inc"))
    Builder(ch).build()
    set_timings(ch)
    ch.write_bba(sys.argv[1])


if __name__ == "__main__":
    main()
