"""XC2064-def.txt: Art und Felder jedes der 11.360 Konfigurationsbits.

Bit i liegt in Rahmen i // 71 an Stelle i % 71, das ist Zeile i // 71 der RBT-Datei (parse.js). Wie in
Shirriffs Decoder (parse.js, clb.js, iob.js) ist ein Bit programmiert, wenn es 0 ist. Die kodierten
Multiplexer (CLB-Eingänge, IOB, Taktpuffer) lesen dagegen den Rohwert: Bit n hat die Wertigkeit 2^n.
"""
import collections
import re

from . import sources

FRAMES, FRAME_BITS = 160, 71
NBITS = FRAMES * FRAME_BITS

# kind und key je Art:
#   unused  ()
#   pip     (g,)              G-Koordinate der Kreuzung zweier Leitungen, z. B. "170G23"
#   switch  (g, p1, p2)       Lage einer Switch-Matrix (Magic-Bit), verbundene Pins 1-8
#   bidi    (g,)              Bedeutung offen (Shirriff dekodiert sie nicht)
#   clbmux  (tile, pin, n)    Eingangs-Mux A, B, C, D oder K einer CLB, Bit n
#   clkmux  (buffer, n)       Eingang der Taktpuffer CLK.AA.I (GCLK) und CLK.II.I (ACLK), Bit n
#   iobmux  (pad, pin, n)     O-, T- oder K-Mux eines IOB; das unbenannte "IOB Pnn" ist T-Bit 0 (iob.js)
#   clb     (tile, name)      übrige CLB-Bits (Logic Table, FF, X/Y ...), name wie in der Datei
#   iob     (pad, name)       übrige IOB-Bits ("I PAD/Latched")
#   other   (name,)           Readback, TTL/CMOS, DONE-Pullup, unbekannte
Entry = collections.namedtuple("Entry", "index text kind key")

_RULES = [
    (r"----- NOT USED -----", "unused", lambda m: ()),
    (r"IOB (P\d+)\.([OTK]) MuxBit: (\d+)", "iobmux", lambda m: (m[1], m[2], int(m[3]))),
    (r"IOB (P\d+)", "iobmux", lambda m: (m[1], "T", 0)),
    (r"IOB (P\d+)\.(.+)", "iob", lambda m: (m[1], m[2])),
    (r"PIP\s+(\d+G\d+)", "pip", lambda m: (m[1],)),
    (r"Bidi\s+(\d+G\d+)", "bidi", lambda m: (m[1],)),
    (r"Magic @ (\d+G\d+) ([1-8]) ([1-8])", "switch", lambda m: (m[1], int(m[2]), int(m[3]))),
    (r"CLB ([A-H][A-H])\.([ABCDK]) MuxBit: (\d+)", "clbmux", lambda m: (m[1], m[2], int(m[3]))),
    (r"CLB (CLK\.[AI][AI]\.I) MuxBit: (\d+)", "clkmux", lambda m: (m[1], int(m[2]))),
    (r"CLB ([A-H][A-H])\s*(.*)", "clb", lambda m: (m[1], m[2])),
    (r"Other (.+)", "other", lambda m: (m[1],)),
]


def _classify(text):
    for pattern, kind, key in _RULES:
        m = re.fullmatch(pattern, text)
        if m:
            return kind, key(m)
    raise ValueError("unbekannter Eintrag in XC2064-def.txt: %r" % text)


def load(path=sources.DEF_TXT):
    """Liste der 11.360 Einträge, Index = Bitnummer. Die Datei endet mit Bit 11.357; fehlende Bits gelten wie
    in parse.js als unbenutzt (Text "(fehlt)", siehe missing())."""
    entries = [None] * NBITS
    for line in sources.read_text(path).splitlines():
        m = re.match(r"Bit:\s+([0-9A-F]+)\s+(.*)", line)
        if not m:
            continue
        i, text = int(m[1], 16), m[2].strip()
        kind, key = _classify(text)
        entries[i] = Entry(i, text, kind, key)
    return [e or Entry(i, "(fehlt)", "unused", ()) for i, e in enumerate(entries)]


def missing(entries):
    return [e.index for e in entries if e.text == "(fehlt)"]


def duplicates(entries):
    """Einträge (außer NOT USED), deren Text mehrfach vorkommt; leer, wenn jeder Name eindeutig ist"""
    count = collections.Counter(e.text for e in entries if e.kind != "unused")
    return sorted(t for t, n in count.items() if n > 1)
