# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""Reading XC2064 bitstreams: .BIT (binary, from XACT) and .RBT (text, from XACT).

Both carry the same data: a 40-bit header (8 ones, 0010, 24-bit length, 1111), then 160 frames
of start bit 0, 71 data bits and the stop bits 111. In the RBT file the header is one line, each
frame is one line, and at the end comes the line 11111111. Before that there are 7 lines of text, e.g.

    Xilinx LCA TEST1.LCA 2064LPC68
    File TEST1.rbt
    Sun May  6 22:39:36 2018
    Sun May  6 22:39:36 2018
    Source
    Version
    Produced by XACT version 5.1.0

raw[i] is data bit i % 71 of frame i // 71, as 0/1 as in the file (0 = programmed).

MAKEBITS 5.2.0 writes a different length counter into the header and 16 instead of 8 ones at the end. Reading
accepts both with a note; writing always uses the header of XACT 5.1.0.
"""
import re

from .bitmap import FRAMES, FRAME_BITS, NBITS

PREAMBLE = "1111111100100000000000101111000011011111"
POSTAMBLE = "11111111"
HEADER = re.compile(r"111111110010[01]{24}1111")  # header with any length counter


class Bitstream:
    def __init__(self, raw, fmt, header=(), notes=()):
        self.raw = raw  # list of 0/1, length NBITS
        self.fmt = fmt  # "BIT" or "RBT"
        self.header = list(header)  # text lines before the header (RBT)
        self.notes = list(notes)  # anomalies found while reading


def _frames(bits, notes):
    raw = []
    for f in range(FRAMES):
        start, data, stop = bits[f][0], bits[f][1:1 + FRAME_BITS], bits[f][1 + FRAME_BITS:]
        if start != "0" or stop != "111":
            raise ValueError("frame %d: start/stop %s/%s instead of 0/111" % (f, start, stop))
        raw += [int(b) for b in data]
    return raw


def _header_notes(header):
    if header == PREAMBLE:
        return []
    return ["length counter %d instead of %d in the header (MAKEBITS 5.2.0?)"
            % (int(header[12:36], 2), int(PREAMBLE[12:36], 2))]


def read_bit(data):
    bits = "".join(format(b, "08b") for b in data)
    if not HEADER.fullmatch(bits[:40]):
        raise ValueError("not an XC2064 bitstream: header %s instead of %s" % (bits[:40], PREAMBLE))
    size = 1 + FRAME_BITS + 3
    body = bits[40:40 + FRAMES * size]
    if len(body) < FRAMES * size:
        raise ValueError("too short: %d instead of %d bits" % (len(bits), 40 + FRAMES * size))
    rest = bits[40 + FRAMES * size:]
    notes = _header_notes(bits[:40])
    if rest:
        notes.append("%d bits after the last frame (%d of them 1), ignored" % (len(rest), rest.count("1")))
    return Bitstream(_frames([body[i * size:(i + 1) * size] for i in range(FRAMES)], notes), "BIT", notes=notes)


def read_rbt(text):
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    heads = [i for i, l in enumerate(lines) if HEADER.fullmatch(l)]
    if not heads:
        raise ValueError("no header line %s" % PREAMBLE)
    head = heads[0]
    frames = lines[head + 1:head + 1 + FRAMES]
    if len(frames) < FRAMES or not all(re.fullmatch(r"[01]{75}", l) for l in frames):
        raise ValueError("expected %d frame lines of 75 characters 0/1 after the header line" % FRAMES)
    notes = _header_notes(lines[head])
    tail = [l for l in lines[head + 1 + FRAMES:] if l]
    if tail != [POSTAMBLE]:
        notes.append("end %r instead of %r" % (tail[:2], [POSTAMBLE]))
    return Bitstream(_frames(frames, notes), "RBT", header=lines[:head], notes=notes)


def read(path):
    data = open(path, "rb").read()
    if path.upper().endswith(".RBT"):
        bs = read_rbt(data.decode("latin-1"))
    else:
        bs = read_bit(data)
    assert len(bs.raw) == NBITS
    return bs


def frames(raw):
    """Header, 160 frame lines and end as lines of 0/1"""
    assert len(raw) == NBITS
    rows = ["0" + "".join(str(b) for b in raw[f * FRAME_BITS:(f + 1) * FRAME_BITS]) + "111" for f in range(FRAMES)]
    return [PREAMBLE] + rows + [POSTAMBLE]


def write_rbt(raw, design, part, when=None):
    """RBT text in exactly the layout of XACT (CRLF, 7 text lines, header, frames, 11111111); part e.g. 2064PC68"""
    import time
    stamp = time.asctime(when or time.localtime())
    head = ["Xilinx LCA %s.LCA %s" % (design.upper(), part), "File %s.rbt" % design, stamp, stamp, "Source",
            "Version", "Produced by xc2064pack (arch/xc2064)"]
    return "\r\n".join(head + frames(raw)) + "\r\n"


def write_bit(raw):
    """BIT: header, frames and end as a bit sequence, padded with 1 to whole bytes (XACT's .BIT also appends
    meaningless fill bytes, which reading ignores)"""
    bits = "".join(frames(raw))
    bits += "1" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
