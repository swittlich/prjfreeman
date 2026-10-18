# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""XC2064-def.txt: kind and fields of each of the 11,360 configuration bits.

Bit i lies in frame i // 71 at position i % 71, that is line i // 71 of the RBT file (parse.js). As in
Shirriff's decoder (parse.js, clb.js, iob.js), a bit is programmed when it is 0. The encoded
multiplexers (CLB inputs, IOB, clock buffers), on the other hand, read the raw value: bit n has the weight 2^n.
"""
import collections
import re

from . import sources

FRAMES, FRAME_BITS = 160, 71
NBITS = FRAMES * FRAME_BITS

# kind and key per kind:
#   unused  ()
#   pip     (g,)              G coordinate of the crossing of two lines, e.g. "170G23"
#   switch  (g, p1, p2)       position of a switch matrix (Magic bit), connected pins 1-8
#   bidi    (g,)              meaning unresolved (Shirriff does not decode them)
#   clbmux  (tile, pin, n)    input mux A, B, C, D or K of a CLB, bit n
#   clkmux  (buffer, n)       input of the clock buffers CLK.AA.I (GCLK) and CLK.II.I (ACLK), bit n
#   iobmux  (pad, pin, n)     O, T or K mux of an IOB; the unnamed "IOB Pnn" is T bit 0 (iob.js)
#   clb     (tile, name)      remaining CLB bits (Logic Table, FF, X/Y ...), name as in the file
#   iob     (pad, name)       remaining IOB bits ("I PAD/Latched")
#   other   (name,)           Readback, TTL/CMOS, DONE pull-up, unknown ones
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
    raise ValueError("unknown entry in XC2064-def.txt: %r" % text)


def load(path=sources.DEF_TXT):
    """List of the 11,360 entries, index = bit number. The file ends with bit 11,357; as in parse.js, missing
    bits are treated as unused (text "(missing)", see missing())."""
    entries = [None] * NBITS
    for line in sources.read_text(path).splitlines():
        m = re.match(r"Bit:\s+([0-9A-F]+)\s+(.*)", line)
        if not m:
            continue
        i, text = int(m[1], 16), m[2].strip()
        kind, key = _classify(text)
        entries[i] = Entry(i, text, kind, key)
    return [e or Entry(i, "(missing)", "unused", ()) for i, e in enumerate(entries)]


def missing(entries):
    return [e.index for e in entries if e.text == "(missing)"]


def duplicates(entries):
    """Entries (except NOT USED) whose text occurs more than once; empty if every name is unique"""
    count = collections.Counter(e.text for e in entries if e.kind != "unused")
    return sorted(t for t, n in count.items() if n > 1)
