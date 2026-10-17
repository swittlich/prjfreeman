# Chip-Datenbank für ein Modell des Xilinx XC2064 (1985, das erste FPGA) als Himbächel-uarch.
#
# Grundlagen: XC2000-Datenblatt; Ken Shirriffs Reverse Engineering (github.com/shirriff/xc2064, als
# Submodule shirriff-xc2064) mit der Bitkarte XC2064-def.txt, den Leitungsnamen (draw.js), den
# CLB-Eingangs-Muxen (clb.js) und den IOB-Muxen (iob.js). Das Paket xc2064db (arch/xc2064/xc2064db) liest
# diese Daten; der Routing-Graph entsteht aus xc2064db.graph, jeder Pip dort entspricht einem Bit bzw.
# einem Mux-Code des Originals (Ausnahme: die Eingänge der Taktpuffer, deren Codes niemand kennt).
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
#     IOBs (iob.js):  O-Mux (Leitungen, X/Y der Rand-CLB, GCLK an P9) und T-Mux (2 Einzelsegmente, 2 Long
#                     Lines; Puffer aus/an ist Konfiguration, kein Pip), I über PIP-Bits auf die Leitungen
#                     beider Kanäle am Pad und fest an die Eingänge der Rand-CLB
#     Taktpuffer:     GCLK von P9, ACLK von P43 (Bits der Eingangs-Muxe CLK.AA.I/CLK.II.I, Code unbekannt)
#     Konstanten:     keine Leitung (wie im Original); pack() faltet sie in LUT-Inhalte oder setzt eine LUT ein
#   Repowering-Puffer an den Sektionsgrenzen sind kein Pip: ein Puffer ist nie aus, seine Richtung folgt aus
#   dem Routing (xc2064db.graph.bidi_bit).
#   Timing: CLB und IOB aus dem Data Book 1994 (Stufen -70, -100, -130, dazu -50 abgeleitet), Interconnect
#   als RC-Modell wie im Datenblatt (Interconnect Performance), siehe DATABOOK und set_timings().
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
LETTERS = "ABCDEFGHI"

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
    """Kachel (x, y), z und Seite eines Pads im Modellraster; z = 1 für das zweite Pad einer Kachel
    ("topright", "rightlower", ...)"""
    r, c = LETTERS.index(tile[0]) + 1, LETTERS.index(tile[1]) + 1
    z = 1 if style in ("topright", "bottomright", "rightlower", "leftlower") else 0
    if style.startswith("top"):
        side, x, y = "T", c, 0
    elif style.startswith("bottom"):
        side, x, y = "B", c, LAST
    elif style.startswith("right"):
        side, x, y = "R", LAST, r
    else:
        side, x, y = "L", 0, r
    return dict(pin=pin, x=x, y=y, z=z, side=side)


PAD_INFO = [pad_info(*p) for p in PADS]


def is_clb(x, y):
    return 1 <= x <= N_CLB and 1 <= y <= N_CLB


def has_sm(x, y):
    return 1 <= x <= LAST and 1 <= y <= LAST


def tile_xy(t):
    """Kachel 'BC' (Zeile B, Spalte C) -> (x, y); '@' ist die Pad-Reihe oben bzw. links (0)"""
    return ord(t[1]) - ord("@"), ord(t[0]) - ord("@")


def tile_name(x, y):
    return chr(ord("@") + y) + chr(ord("@") + x)


PAD_BY_PIN = {p["pin"]: p for p in PAD_INFO}
PAD_SIDE = {p[0]: p[2][0].upper() for p in PADS}  # T, B, L, R


# --- Drahtnamen ---------------------------------------------------------------------------------
REL = {(0, 0): "", (1, 0): "_R", (-1, 0): "_L", (0, -1): "_U", (0, 1): "_D", (-1, 1): "_LD", (1, -1): "_RU"}


def wire_name(node, t):
    """Name des Drahts von Graph-Knoten node in Kachel t. Senkrechte Leitungen V<k>, waagerechte H<k>,
    Long Lines VL<k>/HL<k>; Zusatz _U/_D/_L/_R für das Stück der Nachbarkachel (oben, unten, links,
    rechts). CLB-Pins heißen wie der Pin, X/Y der Nachbar-CLBs XT (X darüber), XB (X darunter), YL (Y links)."""
    if node in ("GCLK", "ACLK"):
        return node
    m = re.fullmatch(r"(P\d+)\.([IOT])", node)
    if m:  # IOB: in der eigenen Kachel die Bel-Drähte (Bel-Pin I = XACT .O), in der CLB der Direkteingang
        p = PAD_BY_PIN[m[1]]
        if tile_xy(t) == (p["x"], p["y"]):
            return "IO%d_%s" % (p["z"], {"O": "I", "I": "O", "T": "T"}[m[2]])
        if m[2] != "I":
            raise ValueError("%s außerhalb der Pad-Kachel" % node)
        return "P" + PAD_SIDE[m[1]]
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
    if cn.kind in ("iobo", "iobt"):  # IOB: in der Kachel des Pads
        p = PAD_BY_PIN[cn.b.split(".")[0]]
        return tile_name(p["x"], p["y"])
    if cn.kind in ("iobi", "clkbuf"):
        p = PAD_BY_PIN[cn.a.split(".")[0]]
        return tile_name(p["x"], p["y"])
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
    """Pip-Klasse: SM (Switch-Matrix) und PIP (PIP-Bit) sind Pass-Transistoren, INMUX die Eingangs-Muxe von
    CLB und IOB, GCLK der Taktpuffer"""
    if cn.kind == "switch":
        return "SM"
    if cn.kind in ("mux", "iobo", "iobt"):
        return "INMUX"
    if cn.kind == "clkbuf":
        return "GCLK"
    return "PIP"


def node_class(node):
    """Knotenklasse für das RC-Modell: Einzelsegment, Long Line, Taktnetz; Pins ohne"""
    if node in ("GCLK", "ACLK"):
        return "CLKNET"
    m = re.fullmatch(r"(col|row)\.[A-I]\.(local|long)\.\d(?:@[A-I])?", node)
    return ("LONG" if m[2] == "long" else "SEG") if m else ""


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
            a, b = wire_name(cn.a, t) if not self.direct_xy(cn) else self.direct_xy(cn), wire_name(cn.b, t)
            for n, w in ((cn.a, a), (cn.b, b)):
                self.wire(xy, w, "ROUTING")
                self.node(n, xy, w)
            cls = timing_class(cn)
            self.pip(xy, a, b, cls)
            if cn.kind in ("pip", "switch", "junction"):  # Pass-Transistor: beide Richtungen
                self.pip(xy, b, a, cls)

    @staticmethod
    def direct_xy(cn):
        """X/Y einer Rand-CLB direkt im Ausgangs-Mux eines IOB: Draht IO<z>_X/Y in der Pad-Kachel"""
        if cn.kind == "iobo" and re.fullmatch(r"[A-H][A-H]\.[XY]", cn.a):
            return "IO%d_%s" % (PAD_BY_PIN[cn.b.split(".")[0]]["z"], cn.a[-1])
        return None

    def clb(self, x, y):
        """Bels und interne Pips einer CLB (LOCAL: Teil der Laufzeit der Logik, XYDRV: Ausgangstreiber)"""
        xy = (x, y)
        for p in "ABCDK":
            self.wire(xy, p, "CLB_IN")
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
                     ("K", "FF_CLK"),
                     ("A", "FF_S"), ("F_O", "FF_S"), ("FG_O", "FF_S"),
                     ("D", "FF_R"), ("G_O", "FF_R"), ("FG_O", "FF_R")):
            self.pip(xy, s, d, "LOCAL")
        for s, cls in (("C", "CLKC"), ("G_O", "CLKG"), ("FG_O", "CLKG")):  # Takt über C bzw. G
            self.pip(xy, s, "FF_CLK", cls)
        bels.append(("FF", "DFF", 3, [("D", "FF_D", PinType.INPUT), ("CLK", "FF_CLK", PinType.INPUT),
                                     ("S", "FF_S", PinType.INPUT), ("R", "FF_R", PinType.INPUT),
                                     ("Q", "Q", PinType.OUTPUT)]))
        for o in "XY":
            for s in ("F_O", "G_O", "FG_O", "Q"):
                self.pip(xy, s, o, "XYDRV")

    def iob(self, p):
        """IOB-Pad: Bel und Drähte. Seine Muxe und Pips kommen aus dem Graphen (iob.js, routing()); der
        Modus an/aus/Tristate folgt aus dem Zelltyp (pack() in xc2064.cc), T hat daher keine Konstanten."""
        xy, z = (p["x"], p["y"]), p["z"]
        for sfx, typ in (("I", "IO_I"), ("T", "IO_T"), ("O", "IO_O"), ("PAD", "IO_PAD")):
            self.wire(xy, "IO%d_%s" % (z, sfx), typ)
        self.bels = getattr(self, "bels", {})
        self.bels.setdefault(xy, []).append((p["pin"], "IOB", z, [
            ("I", "IO%d_I" % z, PinType.INPUT), ("T", "IO%d_T" % z, PinType.INPUT),
            ("O", "IO%d_O" % z, PinType.OUTPUT), ("PAD", "IO%d_PAD" % z, PinType.INOUT)]))

    def build(self):
        ch = self.ch
        self.routing()
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
                    w = tt.create_wire(name, typ)
                    node = self.wire_owner.get((xy, name))
                    if node and len(self.node_wires[node]) == 1 and node_class(node):  # Knoten aus einem Draht
                        w.timing_idx = ch.timing.node_class_idx(node_class(node))
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
                ch.set_tile_type(x, y, "T_X%dY%d" % (x, y))
        for node, wires in self.node_wires.items():
            if len(wires) > 1:
                ch.add_node([NodeWire(x, y, w) for x, y, w in wires], timing_class=node_class(node))


# --- Timing ----------------------------------------------------------------------------------------
# Werte aus dem Xilinx Programmable Logic Data Book 1994, XC2000 "CLB Switching Characteristic Guidelines"
# (S. 2-221) und "IOB Switching Guidelines" (S. 2-222), in ns, Maximalwerte. Die Stufe ist die Umlaufrate
# eines FF in MHz. Die Tabellen von 1994 haben -70, -100, -130; den XC2064 gab es auch als -50 (im PD48
# nur so, S. 2-216). Dessen Werte stehen erst in älteren Data Books, bis dahin -70 mal 70/50.
DATABOOK = {
    #       T_ILO T_QLO T_CKO T_ICK T_CCO T_CIO T_PID T_OP T_THZ T_TON
    "70": (10.0, 6.0, 10.0, 7.0, 13.0, 20.0, 6.0, 9.0, 15.0, 15.0),
    "100": (8.0, 6.0, 7.0, 6.0, 9.0, 13.0, 4.0, 7.0, 11.0, 13.0),
    "130": (5.5, 3.7, 7.0, 2.5, 7.0, 13.0, 3.5, 5.5, 7.0, 11.0),
}
DATABOOK["50"] = tuple(v * 70 / 50 for v in DATABOOK["70"])  # abgeleitet, siehe oben


def clb_timing(t):
    """Tabellenwerte auf das Modell verteilen (ps). T_ILO gilt vom PIP am CLB-Eingang bis zum Ausgang im
    Kanal, schließt also Eingangs-Mux und Ausgangstreiber ein; T_QLO (Q über F/G zum Ausgang) ist die Laufzeit
    der Funktion selbst. Daraus: LUT = T_QLO, Ausgangstreiber = T_ILO - T_QLO, Clock-to-Q = T_CKO - Treiber,
    Setup an D = T_ICK - LUT (nicht negativ), Takt über C bzw. G später als über K."""
    ilo, qlo, cko, ick, cco, cio = t[:6]
    out = ilo - qlo
    ps = lambda v: int(round(max(v, 0) * 1000))  # noqa: E731
    return dict(lut=ps(qlo), out=ps(out), ckq=ps(cko - out), setup=ps(ick - qlo), clk_c=ps(cco - cko),
                clk_g=ps(cio - qlo - cko), pid=ps(t[6]), op=ps(t[7]), tri=ps(max(t[8], t[9])))


# Interconnect: Das Data Book nennt keine Zahlen, nur das Modell ("Interconnect Performance"): eine Kette von
# Pass-Transistoren ist eine Kette von RC-Gliedern (Widerstand jedes Schalters mal die Kapazität dahinter),
# die an jedem Treiber neu beginnt. In nextpnr: Schalter (SM, PIP, Eingangs-Mux) unbuffered mit Widerstand
# R_SW, die Leitungen mit ihrer Kapazität; CLB-Ausgang und Taktpuffer sind Treiber. Geschätzt für -70: ein
# Einzelsegment hinter einem Schalter etwa 0,5 ns, eine Long Line 4 ns, der Taktpuffer 4 ns; die anderen
# Stufen im Verhältnis von T_ILO.
R_SW, R_DRV = 2000000, 1000000  # Milliohm: Pass-Transistor, Ausgangstreiber der CLB
C_SEG, C_LONG = 250, 2000  # Femtofarad: Einzelsegment, Long Line
T_GCLK = 4000  # ps: Taktpuffer


def set_timings(ch: Chip):
    tmg = ch.set_speed_grades(sorted(DATABOOK, key=int))
    for speed, table in DATABOOK.items():
        s = table[0] / DATABOOK["70"][0]  # Interconnect im Verhältnis von T_ILO
        c = clb_timing(table)
        tv = lambda v: TimingValue(int(round(v)))  # noqa: E731
        for name, delay, res, cap, buffered in (
                ("SM", 300 * s, R_SW * s, C_SEG, False), ("PIP", 200 * s, R_SW * s, C_SEG, False),
                ("INMUX", 0, R_SW * s, 0, False), ("GCLK", T_GCLK * s, 0, 0, True),
                ("XYDRV", c["out"], R_DRV * s, 0, True), ("LOCAL", 0, 0, 0, True),
                ("CLKC", c["clk_c"], 0, 0, True), ("CLKG", c["clk_g"], 0, 0, True)):
            tmg.set_pip_class(grade=speed, name=name, delay=tv(delay), in_cap=tv(cap), out_res=tv(res),
                              is_buffered=buffered)
        for name, cap in (("SEG", C_SEG), ("LONG", C_LONG), ("CLKNET", 0)):
            tmg.set_node_class(grade=speed, name=name, delay=TimingValue(0), res=TimingValue(0),
                               cap=TimingValue(cap))
        for cell, n in (("XC2000_LUT3", 3), ("XC2000_LUT4", 4)):  # T_ILO hängt nicht von der Funktion ab
            lut = ch.timing.add_cell_variant(speed, cell)
            for i in range(n):
                lut.add_comb_arc(f"I[{i}]", "O", tv(c["lut"]))
        dff = ch.timing.add_cell_variant(speed, "XC2000_DFF")
        dff.add_setup_hold("CLK", "D", ClockEdge.RISING, tv(c["setup"]), TimingValue(0))
        dff.add_clock_out("CLK", "Q", ClockEdge.RISING, tv(c["ckq"]))
        # IOB: Pad -> Eingang T_PID, Ausgang -> Pad T_OP, T -> Pad der größere von T_THZ und T_TON
        for cell, arcs in (("XC2000_INBUF", (("PAD", "O", "pid"),)),
                           ("XC2000_OUTBUF", (("I", "PAD", "op"),)),
                           ("XC2000_TOBUF", (("I", "PAD", "op"), ("T", "PAD", "tri"))),
                           ("XC2000_IOBUF", (("I", "PAD", "op"), ("T", "PAD", "tri"), ("PAD", "O", "pid")))):
            v = ch.timing.add_cell_variant(speed, cell)
            for a, b, k in arcs:
                v.add_comb_arc(a, b, tv(c[k]))


def main():
    ch = Chip("xc2064", "XC2064", X, Y)
    ch.strs.read_constids(path.join(path.dirname(__file__), "constids.inc"))
    ch.read_gfxids(path.join(path.dirname(__file__), "gfxids.inc"))
    Builder(ch).build()
    set_timings(ch)
    ch.write_bba(sys.argv[1])


if __name__ == "__main__":
    main()
