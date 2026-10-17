"""Konfiguration als lesbare Textdatei (das Format zwischen nextpnr und xc2064pack, Rückweg xc2064unpack).

Eine Zeile je Eintrag, Namen wie bei Shirriff bzw. XACT, '#' leitet einen Kommentar ein:

    device XC2064                   Kopf; package PC68 oder PD48 (Gehäuse, nur für den RBT-Kopf)
    mux AB.A row.A.local.1          CLB-Eingang A..D, K und die gewählte Quellleitung (none: keine)
    mux P59.O col.I.local.4         Ausgangs-Mux eines IOB (Leitung, X/Y einer CLB wie AH.X, GCLK, ACLK)
    mux P59.T col.I.long.2          Tristate-Mux eines IOB: Quelle (Tristate), on (immer aktiv) oder off
    pip col.B.local.1:row.C.local.3 einzelnes PIP-Bit, Kreuzung einer col- mit einer row-Leitung
    switch BC.8.1 1-3               Verbindung zweier Pins einer Switch-Matrix (Magic-Bit)
    bidi 125G6 right                Repowering-Puffer und seine Richtung: down/right (Bit programmiert) oder
                                    up/left; "bidi auto": aus dem Routing ableiten (xc2064pack)
    clb AB BASE:FG F:A:B:C ...      Konfiguration einer CLB (Felder: blocks.py)
    iob P8 I:Q                      Eingang eines IOB direkt (PAD) oder gelatcht (Q), ggf. Takt-Mux K
    other UNknown 2 1               Optionen "Other" (Name, 0/1)
    bit CLB CLK.AA.I MuxBit: 0      jedes andere programmierte Bit mit seinem Namen aus XC2064-def.txt
                                    (nur noch die Eingänge der Taktpuffer, deren Codes niemand kennt)
    port P9 clk input               (nextpnr) Name und Richtung des Top-Level-Ports am Pad, für den Rückweg
    reg AB ctr[0]                   (nextpnr) Name des Netzes am Q des Speicherelements einer CLB, ebenso

decode() liefert jede CLB, jedes IOB, jeden Mux und alle Optionen, dazu jedes programmierte PIP-, Switch-,
Bidi- und sonstige Bit; daraus ergibt sich mit encode() jedes Bit wieder (verlustfrei, geprüft mit allen
XACT-Bitstreams). Fehlt etwas im Text (Ausgabe von nextpnr), gilt der Grundzustand von XACT (blocks.py).
"""
import collections
import re

from . import bitmap, blocks, clbmux, iobmux, lines as lines_mod, switches

Item = collections.namedtuple("Item", "kind name value bits comment")


class Database:
    """Alles, was Dekodierung und Kodierung brauchen, einmal geladen"""

    def __init__(self):
        self.entries = bitmap.load()
        self.lines = lines_mod.Lines()
        self.muxes = clbmux.muxes(self.lines, self.entries)
        self.iobs = iobmux.iobs(self.lines, self.entries)
        self.blocks = blocks.Blocks(self.entries)
        self.switch_pos = {g: name for name, g in switches.positions(self.lines).items()}
        self.mux_bits = {b for m in self.muxes.values() for b in m.bits.values()}
        self.mux_bits |= {b for i in self.iobs.values() for b in list(i.obits.values()) + list(i.tbits.values())}
        bl = self.blocks
        self.block_bits = {b for t in bl.tiles for b in bl.clb_bitset[t]}
        self.block_bits |= {bl.bit("IOB %s.I PAD/Latched" % p) for p in bl.pads}
        self.block_bits |= {b for k in bl.kbits.values() for b in k}
        self.block_bits |= {bl.bit("Other " + o) for o in bl.others}
        # Namen -> Bit für die Kodierung
        self.pip_bit = {self.lines.pip_name(e.key[0]): e.index for e in self.entries if e.kind == "pip"}
        self.switch_bit = {}
        for e in self.entries:
            if e.kind == "switch":
                g, p1, p2 = e.key
                self.switch_bit["%s %d-%d" % (self.switch_pos[g], min(p1, p2), max(p1, p2))] = e.index
        self.bidi_bit = {e.key[0]: e.index for e in self.entries if e.kind == "bidi"}


iob_source_name = iobmux.source_name  # Name einer Quelle des O- bzw. T-Mux im Textformat


def _none_value(m, c):
    """Wert eines Muxes ohne Quelle: "none" für den Grundzustand (kein Bit programmiert), sonst none:Code"""
    return "none" if c == (1 << len(m.bits)) - 1 else "none:%d" % c


def decode(db, raw):
    """(Liste von Item, Liste von Problemen). Problem: programmiertes NOT-USED-Bit, unbekannter Mux-Code
    oder ein PIP, dessen Leitungen nicht bekannt sind."""
    items, problems = [], []
    k_used = {}
    for name, m in sorted(db.muxes.items()):
        try:
            code, src = m.decode(raw)
        except KeyError:
            problems.append("%s: unbekannter Mux-Code %d" % (name, m.code(raw)))
            continue
        if m.pin == "K":
            k_used[m.tile] = src is not None
        items.append(Item("mux", name, src.line if src else _none_value(m, code), sorted(m.bits.values()),
                          "Code %d" % code))
    for pin, iob in sorted(db.iobs.items(), key=lambda kv: int(kv[0][1:])):
        c = iobmux.code(iob.obits, raw)
        if c in iob.omux:
            items.append(Item("mux", pin + ".O", iob_source_name(iob.o[iob.omux[c]]), sorted(iob.obits.values()),
                              "Code %d" % c))
        else:
            problems.append("%s.O: unbekannter Mux-Code %d" % (pin, c))
        c = iobmux.code(iob.tbits, raw)
        if c in iob.tmux:
            value = iob_source_name(iob.t[iob.tmux[c]])
        elif c in (iob.t_off, iob.t_on):
            value = "off" if c == iob.t_off else "on"
        else:
            problems.append("%s.T: unbekannter Code %d" % (pin, c))
            continue
        items.append(Item("mux", pin + ".T", value, sorted(iob.tbits.values()), "Code %d" % c))
    bl = db.blocks
    for t in bl.tiles:
        f = blocks.decode_clb(bl, raw, t, k_used.get(t, False))
        items.append(Item("clb", t, blocks.format_clb(f), bl.clb_bitset[t], None))
    for pin in bl.pads:
        items.append(Item("iob", pin, blocks.format_fields(blocks.decode_iob(bl, raw, pin)), [], None))
    for o in bl.others:
        items.append(Item("other", o, str(1 - raw[bl.bit("Other " + o)]), [bl.bit("Other " + o)], None))
    for e in db.entries:
        if raw[e.index] != 0 or e.index in db.mux_bits or e.index in db.block_bits:
            continue
        if e.kind == "unused":
            problems.append("Bit %d (Rahmen %d, Stelle %d) ist programmiert, laut Bitkarte aber unbenutzt"
                            % (e.index, e.index // bitmap.FRAME_BITS, e.index % bitmap.FRAME_BITS))
        elif e.kind == "pip":
            name = db.lines.pip_name(e.key[0])
            if name is None:
                problems.append("PIP %s (Bit %d): Leitungen unbekannt" % (e.key[0], e.index))
                continue
            items.append(Item("pip", name, None, [e.index], e.key[0]))
        elif e.kind == "switch":
            g, p1, p2 = e.key
            items.append(Item("switch", db.switch_pos[g], "%d-%d" % tuple(sorted((p1, p2))), [e.index], None))
        elif e.kind == "bidi":  # programmiert: der Puffer treibt nach unten bzw. rechts (graph._bidi)
            gx, gy = (int(v) for v in e.key[0].split("G"))
            line = db.lines.col_name.get(gx)
            items.append(Item("bidi", e.key[0], "down" if line else "right", [e.index],
                              line or db.lines.row_name.get(gy)))
        else:
            items.append(Item("bit", e.text, None, [e.index], None))
    return items, problems


ORDER = {"device": 0, "package": 0, "port": 1, "clb": 2, "iob": 3, "mux": 4, "pip": 5, "switch": 6, "bidi": 7,
         "other": 8, "bit": 9}


def format_text(items, source=None, header=()):
    out = ["# XC2064-Konfiguration als Text (arch/xc2064/xc2064db/config.py)"]
    if source:
        out.append("# Quelle: %s" % source)
    out.append("device XC2064")
    out += list(header)
    for it in sorted(items, key=lambda it: (ORDER[it.kind], it.name, it.value or "")):
        line = "%s %s" % (it.kind, it.name) + (" %s" % it.value if it.value else "")
        if it.comment:
            line = "%-44s # %s" % (line, it.comment)
        out.append(line)
    return "\n".join(out) + "\n"


# --- Text -> Bits ------------------------------------------------------------------------------------
Line = collections.namedtuple("Line", "kind name value lineno")


def parse_text(text):
    """Zeilen der Textdatei als Liste von Line (kind, name, value)"""
    out = []
    for n, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        kind, _, rest = line.partition(" ")
        rest = rest.strip()
        if kind in ("mux", "switch", "bidi", "clb", "iob", "port", "reg"):
            name, _, value = rest.partition(" ")
            out.append(Line(kind, name, value.strip(), n))
        elif kind in ("pip", "device", "package", "bit"):
            out.append(Line(kind, rest, "", n))
        elif kind == "other":
            name, _, value = rest.rpartition(" ")
            out.append(Line(kind, name, value, n))
        else:
            raise ValueError("Zeile %d: unbekannte Art %r" % (n, kind))
    return out


def encode(db, lines, defaults=True):
    """Zeilen -> raw (Liste 0/1, 0 = programmiert). defaults: zuerst der Grundzustand von XACT für alles, was
    die Zeilen nicht festlegen. Fehler (ValueError) bei unbekannten Namen, Quellen und Codes."""
    raw = [1] * bitmap.NBITS
    bl = db.blocks

    def put(bits):
        for b, v in bits.items():
            raw[b] = 0 if v else 1

    clb_lines = {l.name: l for l in lines if l.kind == "clb"}
    iob_lines = {l.name: l for l in lines if l.kind == "iob"}
    if defaults:
        for o, v in blocks.OTHER_DEFAULT.items():
            raw[bl.bit("Other " + o)] = 1 - v
        for t in bl.tiles:
            if t not in clb_lines:
                put(blocks.encode_clb(bl, t, blocks.DEFAULT_CLB))
        for pin in bl.pads:
            if pin not in iob_lines:
                put(blocks.encode_iob(bl, pin, blocks.DEFAULT_IOB))
        set_t = {l.name for l in lines if l.kind == "mux"}
        for pin, iob in db.iobs.items():
            if pin + ".T" not in set_t:
                _set_code(raw, iob.tbits, iob.t_off)
    for l in lines:
        try:
            _encode_line(db, raw, l)
        except (KeyError, ValueError) as e:
            raise ValueError("Zeile %d (%s %s %s): %s" % (l.lineno, l.kind, l.name, l.value, e))
    return raw


def _set_code(raw, bits, code):
    for n, b in bits.items():
        raw[b] = (code >> n) & 1


def _encode_line(db, raw, l):
    bl = db.blocks
    if l.kind in ("device", "package", "port", "reg"):
        return
    if l.kind == "mux":
        m = db.muxes.get(l.name)
        if m is not None:
            if l.value.startswith("none"):
                code = int(l.value[5:]) if l.value.startswith("none:") else (1 << len(m.bits)) - 1
                if m.codes.get(code, 0) is not None:
                    raise ValueError("Code %d ist kein none-Code" % code)
            else:
                idx = [i for i, s in enumerate(m.sources) if s.line == l.value]
                codes = [c for c, i in m.codes.items() if idx and i == idx[0]]
                if not codes:
                    raise ValueError("keine Quelle %s" % l.value)
                code = codes[0]
            _set_code(raw, m.bits, code)
            return
        pin, _, which = l.name.partition(".")
        if pin in db.iobs and which in ("O", "T"):
            iob = db.iobs[pin]
            if which == "T" and l.value in ("on", "off"):
                _set_code(raw, iob.tbits, iob.t_on if l.value == "on" else iob.t_off)
                return
            lst, codes, bits = (iob.o, iob.omux, iob.obits) if which == "O" else (iob.t, iob.tmux, iob.tbits)
            found = [c for c, k in codes.items() if iob_source_name(lst[k]) == l.value]
            if not found:
                raise ValueError("keine Quelle %s" % l.value)
            _set_code(raw, bits, found[0])
            return
        if l.name in ("CLK.AA.I", "CLK.II.I"):
            raise ValueError("Code des Taktpuffer-Eingangs unbekannt (kein Bitstream benutzt ihn); "
                             "nextpnr ohne --vopt clkbuf routen")
        raise ValueError("unbekannter Mux")
    if l.kind == "pip":
        raw[db.pip_bit[l.name]] = 0
    elif l.kind == "switch":
        a, b = (int(v) for v in l.value.split("-"))
        raw[db.switch_bit["%s %d-%d" % (l.name, min(a, b), max(a, b))]] = 0
    elif l.kind == "bidi":
        if l.name == "auto":
            return
        if l.value not in ("down", "right", "up", "left"):
            raise ValueError("Richtung %r" % l.value)
        raw[db.bidi_bit[l.name]] = 0 if l.value in ("down", "right") else 1
    elif l.kind == "clb":
        f = dict(blocks.DEFAULT_CLB)
        f.update(blocks.parse_fields(l.value))
        for k, v in blocks.encode_clb(bl, l.name, f).items():
            raw[k] = 0 if v else 1
    elif l.kind == "iob":
        f = dict(blocks.DEFAULT_IOB)
        f.update(blocks.parse_fields(l.value))
        for k, v in blocks.encode_iob(bl, l.name, f).items():
            raw[k] = 0 if v else 1
    elif l.kind == "other":
        raw[bl.bit("Other " + l.name)] = 1 - int(l.value)
    elif l.kind == "bit":
        raw[bl.byname[l.name]] = 0
