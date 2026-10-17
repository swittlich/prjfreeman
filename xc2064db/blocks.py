"""Konfiguration der Logikblöcke (CLB), der IOBs und der übrigen Optionen: Bits <-> Felder.

CLB (37 Bits je CLB, Namen aus XC2064-def.txt, Bedeutung nach Shirriffs clb.js, mit TEST1.LCA geprüft).
Felder wie in XACTs LCA-Datei (Config), dazu BASE und die Tabellen, im Textformat als

    clb AB BASE:FG F:A:B:C G:A:C:Q LUTF:96 LUTG:E8 X:F Y:G Q:FF SET:A RES:D CLK:K:NOT

  BASE   FG (F und G getrennt, Bit BASE FG), F (F und G als eine Funktion von 4 Variablen, B wählt: B = 1
         Tabelle F, B = 0 Tabelle G; beide Eingangs-Muxe gleich) oder FGM (Bit nicht gesetzt, Muxe verschieden)
  F, G   die Eingänge der Funktionsgeneratoren: 1 aus A/B, 2 aus B/C, 3 aus C/D/Q (Mux-Bits, nicht wie bei
         XACT nur die benutzten)
  LUTF/G Wahrheitstabelle, Bit i = Ausgang für Eingang 1 = i & 1, Eingang 2 = (i >> 1) & 1, Eingang 3 = i >> 2
  X, Y   Q, F oder G (UNDEF: beide Bits gesetzt)
  Q      FF oder LATCH (unbenutzte CLBs: LATCH, wie XACT)
  SET    A, F oder leer (BOTH?: beide Bits); RES D, G oder leer (G?: nur Bit D/G)
  CLK    K, C oder G, jeweils mit :NOT, leer (Takt aus) bzw. NOT. Kodierung (aus TEST1.LCA, Shirriffs
         Dekoder verwechselt hier K und G): Bit "CLB AB" wählt C; sonst gilt K, wenn der K-Mux eine Quelle hat,
         und G, wenn nicht, wobei G gegenüber K invertiert ankommt; ein Latch kehrt das Bit CLK Invert um.

IOB (je Pad): "iob P8 I:Q" mit I = PAD (Bit I PAD/Latched gesetzt) oder Q (gelatcht: das FF im Eingang, Takt
von der Leitung der Chipseite). Die O-, T- und K-Muxe stehen als "mux Pnn.O/T/K" (config.py, K nur an P9,
P59, P27, P24: der Takt-Mux der Seite).

Optionen: "other <Name>: 0|1" für die 8 Bits "Other" (DONE-Pull-up, Readback, TTL/CMOS, unbekannte).

Grundzustand (DEFAULTS): was XACT für unbenutzte Blöcke setzt, in allen zehn XACT-Bitstreams gleich.
"""
import re

from . import bitmap

LUT_NAMES = {"F": 1, "G": 2}
CLB_FIELDS = ("BASE", "F", "G", "LUTF", "LUTG", "X", "Y", "Q", "SET", "RES", "CLK")
OTHER_DEFAULT = {  # programmiert in allen XACT-Bitstreams
    "DONE pin Pullup/No Pullup": 1, "UNknown 2": 1,
    "Single/Unlimited FPGA readback if readback enabled": 1, "FPGA readback Enabled/Disable": 1,
}


class Blocks:
    """Bitnummern der Felder je CLB und IOB aus der Bitkarte"""

    def __init__(self, entries=None):
        self.entries = entries or bitmap.load()
        self.byname = {e.text: e.index for e in self.entries if e.kind != "unused"}
        self.tiles = sorted({m[1] for e in self.entries if e.kind == "clb"
                             for m in [re.match(r"CLB ([A-H][A-H])", e.text)] if m})
        self.pads = sorted({m[1] for e in self.entries
                            for m in [re.match(r"IOB (P\d+)\.I PAD/Latched", e.text)] if m}, key=lambda p: int(p[1:]))
        self.others = [e.text[len("Other "):] for e in self.entries if e.kind == "other"]
        self.clb_bitset = {t: self._clb_bits(t) for t in self.tiles}

    def bit(self, name):
        return self.byname[name]

    def _clb_bits(self, t):
        names = ["CLB %s Logic Table: %d Bit: %d" % (t, n, k) for n in (1, 2) for k in range(8)]
        names += ["CLB %s Logic Table: %d %s" % (t, n, s) for n in (1, 2)
                  for s in ("Mux A/B", "Mux B/C", "Mux C/D/Q Bit: 0", "Mux C/D/Q Bit: 1")]
        names += ["CLB %s%s" % (t, s) for s in (
            " BASE FG", " Select Latch/FF", " CLK enable", " CLK Invert", "", " Set A/F", " Set-Enable",
            " Reset-Enable", " Reset D/G", ".X G", ".X F/M or Q", ".Y G", ".Y F/M or Q")]
        return [self.byname[n] for n in names]


def _p(raw, i):
    """programmiert? (Bit 0 im Bitstream)"""
    return 1 - raw[i]


def decode_clb(bl, raw, t, k_used):
    """Felder einer CLB; k_used: hat der K-Mux eine Quelle (entscheidet zwischen K und G)"""
    p = lambda name: _p(raw, bl.bit("CLB %s%s" % (t, name)))  # noqa: E731
    f = {}
    for lut, n in LUT_NAMES.items():
        lt = " Logic Table: %d " % n
        f["LUT" + lut] = "%02X" % sum(p(lt + "Bit: %d" % k) << k for k in range(8))
        i3 = {(1, 0): "C", (0, 1): "D", (0, 0): "Q", (1, 1): "CD?"}[(p(lt + "Mux C/D/Q Bit: 0"), p(lt + "Mux C/D/Q Bit: 1"))]
        f[lut] = "%s:%s:%s" % ("A" if p(lt + "Mux A/B") else "B", "B" if p(lt + "Mux B/C") else "C", i3)
    f["BASE"] = "FG" if p(" BASE FG") else "F" if f["F"] == f["G"] else "FGM"
    f["X"] = ["Q", "F", "G", "UNDEF"][p(".X G") * 2 + p(".X F/M or Q")]
    f["Y"] = ["Q", "G", "F", "UNDEF"][p(".Y F/M or Q") * 2 + p(".Y G")]
    latch = p(" Select Latch/FF")
    f["Q"] = "LATCH" if latch else "FF"
    f["SET"] = ["A", "", "F", "BOTH?"][p(" Set A/F") * 2 + p(" Set-Enable")]
    f["RES"] = ["", "G?", "D", "G"][p(" Reset-Enable") * 2 + p(" Reset D/G")]
    en, sel, inv = p(" CLK enable"), p(""), p(" CLK Invert")
    eff = inv ^ latch
    if not en:  # Takt aus: "", "NOT", "OFF:C", "OFF:C:NOT" (die übrigen Bits so, wie sie stehen)
        f["CLK"] = ":".join((["OFF", "C"] if sel else []) + (["NOT"] if inv else []))
    elif sel:
        f["CLK"] = "C" + (":NOT" if eff else "")
    elif k_used:
        f["CLK"] = "K" + (":NOT" if eff else "")
    else:
        f["CLK"] = "G" + ("" if eff else ":NOT")
    return f


def encode_clb(bl, t, f):
    """Felder -> {Bitnummer: programmiert (0/1)} für alle 37 Bits der CLB"""
    out = {}

    def put(name, v):
        out[bl.bit("CLB %s%s" % (t, name))] = int(v)

    if f["BASE"] == "F" and f["F"] != f["G"]:
        raise ValueError("CLB %s: BASE F verlangt gleiche Eingänge F und G (%s, %s)" % (t, f["F"], f["G"]))
    for lut, n in LUT_NAMES.items():
        lt = " Logic Table: %d " % n
        table = int(f["LUT" + lut], 16)
        for k in range(8):
            put(lt + "Bit: %d" % k, (table >> k) & 1)
        i1, i2, i3 = f[lut].split(":")
        put(lt + "Mux A/B", i1 == "A")
        put(lt + "Mux B/C", i2 == "B")
        b0, b1 = {"C": (1, 0), "D": (0, 1), "Q": (0, 0), "CD?": (1, 1)}[i3]
        put(lt + "Mux C/D/Q Bit: 0", b0)
        put(lt + "Mux C/D/Q Bit: 1", b1)
    put(" BASE FG", f["BASE"] == "FG")
    x = ["Q", "F", "G", "UNDEF"].index(f["X"])
    put(".X G", x >> 1), put(".X F/M or Q", x & 1)
    y = ["Q", "G", "F", "UNDEF"].index(f["Y"])
    put(".Y F/M or Q", y >> 1), put(".Y G", y & 1)
    latch = f["Q"] == "LATCH"
    put(" Select Latch/FF", latch)
    s = ["A", "", "F", "BOTH?"].index(f["SET"])
    put(" Set A/F", s >> 1), put(" Set-Enable", s & 1)
    r = ["", "G?", "D", "G"].index(f["RES"])
    put(" Reset-Enable", r >> 1), put(" Reset D/G", r & 1)
    parts = f["CLK"].split(":") if f["CLK"] else []
    inv = "NOT" in parts
    if not parts or parts[0] in ("NOT", "OFF"):  # Takt aus
        en, sel, ibit = 0, "C" in parts, inv
    elif parts[0] in ("C", "K"):
        en, sel, ibit = 1, parts[0] == "C", inv ^ latch
    elif parts[0] == "G":
        en, sel, ibit = 1, 0, (not inv) ^ latch
    else:
        raise ValueError("CLB %s: CLK %r" % (t, f["CLK"]))
    put(" CLK enable", en), put("", sel), put(" CLK Invert", ibit)
    return out


def format_clb(f):
    return " ".join("%s:%s" % (k, f[k]) for k in CLB_FIELDS)


def format_fields(f):
    return " ".join("%s:%s" % kv for kv in f.items())


def parse_fields(text):
    """'BASE:FG F:A:B:C ... CLK:K:NOT' -> dict (Werte dürfen ':' enthalten)"""
    f = {}
    for tok in text.split():
        k, _, v = tok.partition(":")
        f[k] = v
    return f


def decode_iob(bl, raw, pin):
    return {"I": "PAD" if _p(raw, bl.bit("IOB %s.I PAD/Latched" % pin)) else "Q"}


def encode_iob(bl, pin, f):
    if set(f) - {"I"}:
        raise ValueError("IOB %s: unbekannte Felder %s (Takt-Mux jetzt als mux %s.K)" % (pin, sorted(set(f) - {"I"}), pin))
    return {bl.bit("IOB %s.I PAD/Latched" % pin): int(f.get("I", "PAD") == "PAD")}


DEFAULT_CLB = {"BASE": "FG", "F": "B:C:Q", "G": "B:C:Q", "LUTF": "00", "LUTG": "00", "X": "Q", "Y": "Q",
               "Q": "LATCH", "SET": "", "RES": "", "CLK": ""}
DEFAULT_IOB = {"I": "PAD"}


def lut_inputs(f, lut):
    """Eingänge eines Funktionsgenerators als Liste ['A', 'B', 'Q']"""
    return f[lut].split(":")
