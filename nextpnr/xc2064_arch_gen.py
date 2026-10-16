# Chip-Datenbank für ein Modell des Xilinx XC2064 (1985, das erste FPGA) als Himbächel-uarch.
#
# Grundlagen: XC2000-Datenblatt; Ken Shirriff, "Reverse-engineering the first FPGA chip, the XC2064"
# (righto.com, 2020) und sein Bitstream-Decoder github.com/shirriff/xc2064 (clb.js, iob.js), aus dem
# die Eingangsmultiplexer der LUTs, die FF-/Latch-Optionen und die Pad-Tabelle (PLCC68) stammen.
# Das Routing zwischen den Kacheln ist vereinfacht; ein echter Bitstream entsteht nicht.
#
# Raster (x, y; y nach unten): 8x8 CLBs bei x, y = 1..8 und ein IO-Ring bei 0 bzw. 9. Shirriffs 9x9
# Kacheln AA..II entsprechen x, y = 1..9: jede enthält die Kanäle oberhalb und links ihrer CLB und an
# deren Kreuzung zwei Switch-Matrizen. Die 9. Spalte/Zeile (I) enthält nur Routing und Pads.
#
#   CLB (laut Decoder):
#     Eingänge A, B, C, D, Takt K (aus den globalen Netzen GCLK oder ACLK); Ausgänge X, Y
#     F, G  : je eine Funktion von 3 Variablen; Eingang 1 aus {A, B}, 2 aus {B, C}, 3 aus {C, D, Q}
#     FG    : F und G gemeinsam als eine Funktion von 4 Variablen, B wählt zwischen ihnen
#     FF    : Flipflop oder Latch; Daten aus F (bzw. FG); Takt aus K, C oder G (invertierbar);
#             asynchrones Set aus A oder F, asynchrones Reset aus D oder G
#     X, Y  : je aus Q, F oder G
#   Routing:
#     Einzelsegmente: 4 Leitungen je Kanal zwischen benachbarten Switch-Matrizen
#     Switch-Matrix:  2 je Kreuzung, 8 Pins (2 je Seite), jeder Pin mit 5 der 7 anderen verbindbar
#     IOBs:           wie im Original (Shirriffs iob.js) am Kanalstück parallel zum Rand neben einer
#                     Rand-CLB: das erste Pad einer Kachel am eigenen Stück, das zweite am vorherigen.
#                     Ausgang zum Pad (Bel-Pin I) und Tristate T wählen aus den 4 Spuren und der Long
#                     Line des Randkanals, der Eingang vom Pad (Bel-Pin O) treibt Spuren und Long Line. Direktverbindungen (Datenblatt "Direct Interconnect", iob.js): rechts nimmt
#                     das erste Pad X und Y der CLB links; links treibt das zweite Pad B der CLB rechts;
#                     oben treibt das erste Pad B der CLB darunter und das zweite nimmt deren X; unten
#                     treibt das erste Pad C und D der CLB darüber und das zweite nimmt deren X.
#     Ausgänge:       X und Y in den Kanal rechts der CLB, X an V2/V4 und die 1. vertikale Long Line,
#                     Y an V1/V3 und die 2. (Shirriffs Bitmap; V5 fehlt im Modell, siehe Einzelsegmente)
#     Eingänge:       A aus dem Kanal oberhalb und der Long Line der eigenen Zeile, D aus dem Kanal
#                     unterhalb und der Long Line der Zeile darunter, B/C aus dem Kanal links
#     Direkt:         X -> C/D der CLB darüber und A/B der CLB darunter, Y -> B der CLB rechts
#                     (Datenblatt, "Direct Interconnect")
#     Long Lines:     1 horizontale je Zeile, 2 vertikale je Spalte (auch Zeile/Spalte I), bis zu den Pads
#     Takt:           GCLK von Pin P9 (oben links), ACLK von Pin P43 (unten rechts)
from os import path
import sys
sys.path.append(path.join(path.dirname(__file__), "../.."))
from himbaechel_dbgen.chip import *

N_CLB = 8
X = N_CLB + 2
Y = N_CLB + 2
LAST = N_CLB + 1           # Index der 9. Switch-Matrix-Spalte/-Zeile
N_SM = 2                   # Switch-Matrizen pro Kreuzung
N_SMPIN = 2                # Pins pro Seite und Matrix -> 4 Leitungen je Kanal
SIDES = "NESW"
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
TRACKS = [(m, k) for m in range(N_SM) for k in range(N_SMPIN)]
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


def sm_pin(m, side, k):
    return f"SM{m}_{side}{k}"


def is_clb(x, y):
    return 1 <= x <= N_CLB and 1 <= y <= N_CLB


def has_sm(x, y):
    """Kanalkreuzung mit Switch-Matrizen: Kacheln x, y = 1..9 (Shirriffs AA..II)."""
    return 1 <= x <= LAST and 1 <= y <= LAST


def is_io(x, y):
    return not is_clb(x, y) and (has_sm(x, y) or any(p["x"] == x and p["y"] == y for p in PAD_INFO)
                                 or (x == 0 and 1 <= y <= N_CLB) or (y == 0 and 1 <= x <= LAST))


def pad_access(side, seg, m, k):
    """Zugänge der Pads, die am Randkanalstück (side, seg) hängen, zu dessen Spur (m, k)."""
    return [NodeWire(p["x"], p["y"], f"IO{p['z']}_T{m}{k}") for p in PAD_INFO
            if side and p["side"] == side and p["seg"] == seg]


def edge_pad(side, z, seg):
    """Pad z am Randkanalstück (side, seg), falls es das Pad gibt."""
    return next((p for p in PAD_INFO if p["side"] == side and p["z"] == z and p["seg"] == seg), None)


# Direktverbindungen zwischen Rand-CLB und IOB: (Seite, z, Richtung, CLB-Draht bzw. IOB-Draht).
# "in": Eingang vom Pad -> CLB-Pins (Draht in der CLB-Kachel), "out": X der CLB -> Ausgang zum Pad.
# Das IOB oben verhält sich wie eine CLB darüber, das unten wie eine darunter (Datenblatt).
PAD_DIRECT = [
    ("L", 1, "in", "PL"),     # leftlower -> B
    ("T", 0, "in", "PT"),     # topleft -> B
    ("B", 0, "in", "PB"),     # bottomleft -> C, D
    ("T", 1, "out", "IO1_X"), # X -> topright
    ("B", 1, "out", "IO1_X"), # X -> bottomright
    ("R", 0, "out", "IO0_X"), # X (und Y) -> rightupper
]


def edge_clb(side, seg):
    """Rand-CLB neben dem Randkanalstück (side, seg)."""
    return {"L": (1, seg), "R": (N_CLB, seg), "T": (seg, 1), "B": (seg, N_CLB)}[side]


def create_switch_matrices(tt: TileType):
    for m in range(N_SM):
        for s in SIDES:
            for k in range(N_SMPIN):
                tt.create_wire(sm_pin(m, s, k), "SM_PIN")
    # Pass-Transistoren sind bidirektional -> Pips in beide Richtungen. Nicht verbindbar sind
    # der Partner auf derselben Seite und die "gekreuzte Gerade" (N0-S1, N1-S0, E0-W1, E1-W0).
    pins = [(s, k) for s in SIDES for k in range(N_SMPIN)]
    for m in range(N_SM):
        for (s1, k1) in pins:
            for (s2, k2) in pins:
                if s1 == s2 or (s2 == OPP[s1] and k2 != k1):
                    continue
                tt.create_pip(sm_pin(m, s1, k1), sm_pin(m, s2, k2), timing_class="SM")
        tt.create_group(f"SM{m}", "SWITCHBOX")


def create_long_lines(tt: TileType):
    for w in ("LH", "LV0", "LV1"):
        tt.create_wire(w, "LONG")


def create_constants(tt: TileType):
    tt.create_wire("GND", "GND", const_value="GND")
    tt.create_wire("VCC", "VCC", const_value="VCC")


def create_clb_tiletype(ch: Chip):
    tt = ch.create_tile_type("CLB")
    create_switch_matrices(tt)
    tt.create_group("CLB", "CLB_FRAME")  # nur für die GUI: Rahmen der CLB
    create_long_lines(tt)
    create_constants(tt)
    tt.create_wire("GCLK", "GCLK")
    tt.create_wire("ACLK", "GCLK")
    # Kanäle unterhalb (BOT) und rechts (RGT) der CLB gehören zu Nachbarkacheln -> über Knoten
    for (m, k) in TRACKS:
        tt.create_wire(f"BOT{m}{k}", "CHAN_ACCESS")
        tt.create_wire(f"RGT{m}{k}", "CHAN_ACCESS")
    for p in "ABCDK":
        tt.create_wire(p, "CLB_IN")
    tt.create_wire("X", "CLB_OUT")
    tt.create_wire("Y", "CLB_OUT")
    tt.create_wire("XT", "DIRECT")  # X der CLB darüber
    tt.create_wire("XB", "DIRECT")  # X der CLB darunter
    tt.create_wire("YL", "DIRECT")  # Y der CLB links
    tt.create_wire("PL", "DIRECT")  # Eingang vom Pad links (Rand-CLB, Spalte 1)
    tt.create_wire("PT", "DIRECT")  # ... vom Pad oben (Zeile 1)
    tt.create_wire("PB", "DIRECT")  # ... vom Pad unten (Zeile 8)
    # Long Lines der Nachbarn: horizontale der Zeile darunter (für D), vertikale der Spalte rechts (X, Y)
    tt.create_wire("LHB", "LONG_ACCESS")
    tt.create_wire("RLV0", "LONG_ACCESS")
    tt.create_wire("RLV1", "LONG_ACCESS")
    tt.create_wire("Q", "FF_Q")     # FF-Ausgang, auch Rückführung in F/G

    # Eingangsmultiplexer der CLB-Pins
    top = [sm_pin(m, "E", k) for (m, k) in TRACKS]   # Kanal oberhalb der CLB
    left = [sm_pin(m, "S", k) for (m, k) in TRACKS]  # Kanal links der CLB
    bot = [f"BOT{m}{k}" for (m, k) in TRACKS]
    sources = {
        "A": top + ["XT", "LH"],
        "B": left + ["XT", "YL", "LV0", "PL", "PT"],
        "C": left + ["XB", "LV1", "PB"],
        "D": bot + ["XB", "LHB", "PB"],
    }
    for pin, srcs in sources.items():
        for s in srcs:
            tt.create_pip(s, pin, timing_class="INMUX")
        tt.create_pip("GND", pin)
        tt.create_pip("VCC", pin)
    tt.create_pip("GCLK", "K", timing_class="GCLK")
    tt.create_pip("ACLK", "K", timing_class="GCLK")

    # Funktionsgeneratoren: Eingangsmultiplexer wie im Original (Shirriffs clb.js)
    lut_in = [("A", "B"), ("B", "C"), ("C", "D", "Q")]
    for name, z, n in (("F", 0, 3), ("G", 1, 3), ("FG", 2, 4)):
        bel = tt.create_bel(name, f"LUT{n}", z=z)
        for i in range(n):
            w = f"{name}_I{i}"
            tt.create_wire(w, "LUT_IN")
            tt.add_bel_pin(bel, f"I[{i}]", w, PinType.INPUT)
            for s in (lut_in[i] if i < 3 else ("B",)):  # FG: I[3] = B wählt zwischen F und G
                tt.create_pip(s, w, timing_class="LOCAL")
        tt.create_wire(f"{name}_O", "LUT_OUT")
        tt.add_bel_pin(bel, "O", f"{name}_O", PinType.OUTPUT)

    # Speicherelement (FF oder Latch): Daten aus F/FG, Takt aus K/C/G, Set aus A/F, Reset aus D/G
    for w in ("FF_D", "FF_CLK", "FF_S", "FF_R"):
        tt.create_wire(w, "FF_IN")
    for s, d in (("F_O", "FF_D"), ("FG_O", "FF_D"),
                 ("K", "FF_CLK"), ("C", "FF_CLK"), ("G_O", "FF_CLK"), ("FG_O", "FF_CLK"),
                 ("A", "FF_S"), ("F_O", "FF_S"), ("FG_O", "FF_S"),
                 ("D", "FF_R"), ("G_O", "FF_R"), ("FG_O", "FF_R")):
        tt.create_pip(s, d, timing_class="LOCAL")
    ff = tt.create_bel("FF", "DFF", z=3)
    for pin, w in (("D", "FF_D"), ("CLK", "FF_CLK"), ("S", "FF_S"), ("R", "FF_R")):
        tt.add_bel_pin(ff, pin, w, PinType.INPUT)
    tt.add_bel_pin(ff, "Q", "Q", PinType.OUTPUT)

    # Ausgangsmultiplexer und Ausgänge in den Kanal rechts: Spuren (m, k) = V1 (0,0), V2 (0,1),
    # V3 (1,0), V4 (1,1); X an V2/V4 und RLV0, Y an V1/V3 und RLV1
    for o in ("X", "Y"):
        for s in ("F_O", "G_O", "FG_O", "Q"):
            tt.create_pip(s, o, timing_class="LOCAL")
    for (m, k) in TRACKS:
        tt.create_pip("X" if k else "Y", f"RGT{m}{k}", timing_class="OUTDRV")
    tt.create_pip("X", "RLV0", timing_class="LONGDRV")
    tt.create_pip("Y", "RLV1", timing_class="LONGDRV")
    return tt


def create_io_tiletype(ch: Chip, x: int, y: int):
    """Jede IO-Kachel hat ihren eigenen Typ, weil die Bels nach den PLCC68-Pins benannt sind."""
    tt = ch.create_tile_type(f"IO_X{x}Y{y}")
    if has_sm(x, y):
        create_switch_matrices(tt)
    create_long_lines(tt)
    create_constants(tt)
    for p in (p for p in PAD_INFO if p["x"] == x and p["y"] == y):
        z = p["z"]
        for sfx, typ in (("I", "IO_I"), ("T", "IO_T"), ("O", "IO_O"), ("PAD", "IO_PAD")):
            tt.create_wire(f"IO{z}_{sfx}", typ)
        io = tt.create_bel(p["pin"], "IOB", z=z)
        tt.add_bel_pin(io, "I", f"IO{z}_I", PinType.INPUT)
        tt.add_bel_pin(io, "T", f"IO{z}_T", PinType.INPUT)
        tt.add_bel_pin(io, "O", f"IO{z}_O", PinType.OUTPUT)
        tt.add_bel_pin(io, "PAD", f"IO{z}_PAD", PinType.INOUT)
        # Zugang zum Kanalstück parallel zum Rand (Knoten mit dessen Switch-Matrix-Pins) und zur Long
        # Line des Randkanals: waagerecht oben/unten, die beiden senkrechten links/rechts
        longs = ["LV0", "LV1"] if p["side"] in "LR" else ["LH"]
        tracks = [f"IO{z}_T{m}{k}" for (m, k) in TRACKS]
        for c in tracks:
            tt.create_wire(c, "PAD_ACCESS")
        for c in tracks + longs:
            tt.create_pip(c, f"IO{z}_I", timing_class="INMUX")
            tt.create_pip(f"IO{z}_O", c, timing_class="OUTDRV")
        # Tristate aus den Spuren und der Long Line des Randkanals oder fest. Im Original (iob.js) hat T
        # oben 2 lokale Leitungen und 2 Long Lines, ein gemeinsames Enable (Bus) läuft über die Long Line.
        for c in tracks + longs:
            tt.create_pip(c, f"IO{z}_T", timing_class="INMUX")
        for c in ("GND", "VCC"):
            tt.create_pip(c, f"IO{z}_I")
            tt.create_pip(c, f"IO{z}_T")
        # Direktverbindung von X (rechts auch Y) der Rand-CLB in den Ausgangsmultiplexer
        outs = ["X", "Y"] if p["side"] == "R" else ["X"]
        if any(d[:3] == (p["side"], z, "out") for d in PAD_DIRECT):
            for o in outs:
                tt.create_wire(f"IO{z}_{o}", "DIRECT")
                tt.create_pip(f"IO{z}_{o}", f"IO{z}_I", timing_class="INMUX")
        # Taktpuffer an den Pads P9 (GCLK) und P43 (ACLK)
        if p["pin"] in (GCLK_PIN, ACLK_PIN):
            src = "GCLK_SRC" if p["pin"] == GCLK_PIN else "ACLK_SRC"
            tt.create_wire(src, "GCLK")
            tt.create_pip(f"IO{z}_O", src, timing_class="GCLK")
    return tt


def create_corner_tiletype(ch: Chip):
    tt = ch.create_tile_type("CORNER")
    create_constants(tt)
    gnd = tt.create_bel("GND_DRV", "GND_DRV", z=0)
    tt.add_bel_pin(gnd, "GND", "GND", PinType.OUTPUT)
    vcc = tt.create_bel("VCC_DRV", "VCC_DRV", z=1)
    tt.add_bel_pin(vcc, "VCC", "VCC", PinType.OUTPUT)


def create_nodes(ch: Chip):
    for y in range(Y):
        for x in range(X):
            for (m, k) in TRACKS:
                # horizontales Einzelsegment oberhalb der CLB (x, y): Matrix (x, y) -> Matrix (x+1, y)
                if has_sm(x, y) and has_sm(x + 1, y):
                    node = [NodeWire(x, y, sm_pin(m, "E", k)), NodeWire(x + 1, y, sm_pin(m, "W", k))]
                    if is_clb(x, y - 1):  # ... = Kanal unterhalb der CLB (x, y-1)
                        node.append(NodeWire(x, y - 1, f"BOT{m}{k}"))
                    node += pad_access("T" if y == 1 else "B" if y == LAST else None, x, m, k)
                    ch.add_node(node)
                # vertikales Einzelsegment links der CLB (x, y): Matrix (x, y) -> Matrix (x, y+1)
                if has_sm(x, y) and has_sm(x, y + 1):
                    node = [NodeWire(x, y, sm_pin(m, "S", k)), NodeWire(x, y + 1, sm_pin(m, "N", k))]
                    if is_clb(x - 1, y):  # ... = Kanal rechts der CLB (x-1, y)
                        node.append(NodeWire(x - 1, y, f"RGT{m}{k}"))
                    node += pad_access("L" if x == 1 else "R" if x == LAST else None, y, m, k)
                    ch.add_node(node)
            # Direktverbindungen zu den Nachbar-CLBs
            if is_clb(x, y):
                node = [NodeWire(x, y, "X")]
                if is_clb(x, y + 1):
                    node.append(NodeWire(x, y + 1, "XT"))
                if is_clb(x, y - 1):
                    node.append(NodeWire(x, y - 1, "XB"))
                # ... und zu den IOBs am Rand, die X direkt nehmen (rechts auch Y)
                rp = None
                for side, z, d, w in PAD_DIRECT:
                    p = edge_pad(side, z, y if side in "LR" else x)
                    if d == "out" and p and edge_clb(side, p["seg"]) == (x, y):
                        node.append(NodeWire(p["x"], p["y"], w))
                        rp = p if side == "R" else rp
                if len(node) > 1:
                    ch.add_node(node)
                if is_clb(x + 1, y):
                    ch.add_node([NodeWire(x, y, "Y"), NodeWire(x + 1, y, "YL")])
                elif rp:
                    ch.add_node([NodeWire(x, y, "Y"), NodeWire(rp["x"], rp["y"], "IO0_Y")])
    # Eingänge der Pads direkt auf Pins der Rand-CLB
    for side, z, d, w in PAD_DIRECT:
        for p in PAD_INFO:
            if d == "in" and p["side"] == side and p["z"] == z:
                cx, cy = edge_clb(side, p["seg"])
                ch.add_node([NodeWire(p["x"], p["y"], f"IO{z}_O"), NodeWire(cx, cy, w)])
    # Long Lines über das ganze Routing-Feld (Kacheln 1..9, von Randkanal zu Randkanal); die der Zeile
    # darunter erreicht D, die der Spalte rechts X und Y, die der Randkanäle die Pads (oben über die
    # LH der Pad-Kacheln, links über deren LV)
    for y in range(1, LAST + 1):
        ch.add_node([NodeWire(x, y, "LH") for x in range(1, X) if is_clb(x, y) or is_io(x, y)]
                    + [NodeWire(x, y - 1, "LHB") for x in range(X) if is_clb(x, y - 1)]
                    + ([NodeWire(x, 0, "LH") for x in range(X) if is_io(x, 0)] if y == 1 else []))
    for x in range(1, LAST + 1):
        for i, v in enumerate(("LV0", "LV1")):
            ch.add_node([NodeWire(x, y, v) for y in range(1, Y) if is_clb(x, y) or is_io(x, y)]
                        + [NodeWire(x - 1, y, f"RLV{i}") for y in range(Y) if is_clb(x - 1, y)]
                        + ([NodeWire(0, y, v) for y in range(Y) if is_io(0, y)] if x == 1 else []))
    # Globale Taktnetze: GCLK von P9, ACLK von P43 -> K aller CLBs
    clbs = [(x, y) for x in range(1, N_CLB + 1) for y in range(1, N_CLB + 1)]
    for net, pin in (("GCLK", GCLK_PIN), ("ACLK", ACLK_PIN)):
        p = next(p for p in PAD_INFO if p["pin"] == pin)
        ch.add_node([NodeWire(p["x"], p["y"], f"{net}_SRC")] + [NodeWire(x, y, net) for (x, y) in clbs])


def set_timings(ch: Chip):
    # Größenordnung XC2064-70 (1985): Logik ~15 ns, Pass-Transistoren einige ns (Werte in ps)
    speed = "DEFAULT"
    tmg = ch.set_speed_grades([speed])
    for name, delay in (("SM", 2500), ("INMUX", 1500), ("LOCAL", 500), ("OUTDRV", 1500),
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
    create_clb_tiletype(ch)
    create_corner_tiletype(ch)
    for x in range(X):
        for y in range(Y):
            if is_clb(x, y):
                ch.set_tile_type(x, y, "CLB")
            elif is_io(x, y):
                create_io_tiletype(ch, x, y)
                ch.set_tile_type(x, y, f"IO_X{x}Y{y}")
            else:
                ch.set_tile_type(x, y, "CORNER")
    create_nodes(ch)
    set_timings(ch)
    ch.write_bba(sys.argv[1])


if __name__ == "__main__":
    main()
