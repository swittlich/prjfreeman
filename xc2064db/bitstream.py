"""Bitstreams des XC2064 lesen: .BIT (binär, von XACT) und .RBT (Text, von XACT).

Beide tragen dieselben Daten: einen 40-Bit-Kopf (8 Einsen, 0010, 24 Bit Länge, 1111), dann 160 Rahmen
aus Startbit 0, 71 Datenbits und den Stoppbits 111. In der RBT-Datei steht der Kopf als eine Zeile, jeder
Rahmen als eine Zeile, am Ende die Zeile 11111111. Davor stehen 7 Zeilen Text, z. B.

    Xilinx LCA TEST1.LCA 2064LPC68
    File TEST1.rbt
    Sun May  6 22:39:36 2018
    Sun May  6 22:39:36 2018
    Source
    Version
    Produced by XACT version 5.1.0

raw[i] ist Datenbit i % 71 von Rahmen i // 71, als 0/1 wie in der Datei (0 = programmiert).
"""
import re

from .bitmap import FRAMES, FRAME_BITS, NBITS

PREAMBLE = "1111111100100000000000101111000011011111"
POSTAMBLE = "11111111"


class Bitstream:
    def __init__(self, raw, fmt, header=(), notes=()):
        self.raw = raw  # Liste von 0/1, Länge NBITS
        self.fmt = fmt  # "BIT" oder "RBT"
        self.header = list(header)  # Textzeilen vor dem Kopf (RBT)
        self.notes = list(notes)  # Auffälligkeiten beim Lesen


def _frames(bits, notes):
    raw = []
    for f in range(FRAMES):
        start, data, stop = bits[f][0], bits[f][1:1 + FRAME_BITS], bits[f][1 + FRAME_BITS:]
        if start != "0" or stop != "111":
            raise ValueError("Rahmen %d: Start/Stopp %s/%s statt 0/111" % (f, start, stop))
        raw += [int(b) for b in data]
    return raw


def read_bit(data):
    bits = "".join(format(b, "08b") for b in data)
    if not bits.startswith(PREAMBLE):
        raise ValueError("kein XC2064-Bitstream: Kopf %s statt %s" % (bits[:40], PREAMBLE))
    size = 1 + FRAME_BITS + 3
    body = bits[40:40 + FRAMES * size]
    if len(body) < FRAMES * size:
        raise ValueError("zu kurz: %d statt %d Bits" % (len(bits), 40 + FRAMES * size))
    rest = bits[40 + FRAMES * size:]
    notes = []
    if rest:
        notes.append("%d Bits nach dem letzten Rahmen (%d davon 1), ignoriert" % (len(rest), rest.count("1")))
    return Bitstream(_frames([body[i * size:(i + 1) * size] for i in range(FRAMES)], notes), "BIT", notes=notes)


def read_rbt(text):
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    if PREAMBLE not in lines:
        raise ValueError("keine Kopfzeile %s" % PREAMBLE)
    head = lines.index(PREAMBLE)
    frames = lines[head + 1:head + 1 + FRAMES]
    if len(frames) < FRAMES or not all(re.fullmatch(r"[01]{75}", l) for l in frames):
        raise ValueError("erwartet %d Rahmenzeilen aus 75 Zeichen 0/1 nach der Kopfzeile" % FRAMES)
    notes = []
    tail = [l for l in lines[head + 1 + FRAMES:] if l]
    if tail != [POSTAMBLE]:
        notes.append("Ende %r statt %r" % (tail[:2], [POSTAMBLE]))
    return Bitstream(_frames(frames, notes), "RBT", header=lines[:head], notes=notes)


def read(path):
    data = open(path, "rb").read()
    if path.upper().endswith(".RBT"):
        bs = read_rbt(data.decode("latin-1"))
    else:
        bs = read_bit(data)
    assert len(bs.raw) == NBITS
    return bs
