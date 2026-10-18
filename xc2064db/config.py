"""Configuration as a readable text file (the format between nextpnr and xc2064pack; way back: xc2064unpack).

One line per entry, names as in Shirriff or XACT, '#' starts a comment:

    device XC2064                   header; package PC68, PD48, PC44 or PG68 (chip package, only for the RBT header)
    mux AB.A row.A.local.1          CLB input A..D, K and the selected source line (none: no source)
    mux P59.O col.I.local.4         output mux of an IOB (line, X/Y of a CLB such as AH.X, GCLK, ACLK)
    mux P59.T col.I.long.2          tristate mux of an IOB: source (tristate), on (always active) or off
    mux P9.K row.A.local.1          clock mux of the latched inputs of a chip side (P9 top, P59 right,
                                    P27 bottom, P24 left): source line or GCLK
    mux CLK.AA.I P9                 input of the clock buffer GCLK (CLK.AA.I) or ACLK (CLK.II.I): line,
                                    pad (P9, P11 or P43, P46) or OSC (crystal oscillator, ACLK only)
    pip col.B.local.1:row.C.local.3 single PIP bit, crossing of a col line with a row line
    switch BC.8.1 1-3               connection of two pins of a switch matrix (magic bit)
    bidi 125G6 right                repowering buffer and its direction: down/right (bit programmed) or
                                    up/left; "bidi auto": derive it from the routing (xc2064pack)
    clb AB BASE:FG F:A:B:C ...      configuration of a CLB (fields: blocks.py)
    iob P8 I:Q                      input of an IOB direct (PAD) or latched (Q, FF in the IOB)
    other UNknown 2 1               options "Other" (name, 0/1)
    bit <name>                      any other programmed bit with its name from XC2064-def.txt (since the
                                    codes of the clock buffers are known, there are none left)
    port P9 clk input               (nextpnr) name and direction of the top-level port at the pad, for the way back
    reg AB ctr[0]                   (nextpnr) name of the net at Q of the storage element of a CLB or at the
                                    latched input of a pad (reg P8 s1[0]), likewise

decode() yields every CLB, every IOB, every mux and all options, plus every programmed PIP, switch, bidi and
other bit; from these, encode() gives back every bit (lossless, checked with all XACT bitstreams). Whatever is
missing in the text (output of nextpnr) gets XACT's default state (blocks.py).
"""
import collections

from . import bitmap, blocks, clbmux, iobmux, lines as lines_mod, switches

Item = collections.namedtuple("Item", "kind name value bits comment")


class Database:
    """Everything that decoding and encoding need, loaded once"""

    def __init__(self):
        self.entries = bitmap.load()
        self.lines = lines_mod.Lines()
        self.muxes = clbmux.muxes(self.lines, self.entries)
        self.iobs = iobmux.iobs(self.lines, self.entries)
        self.kmuxes = iobmux.kmuxes(self.lines, self.entries)
        self.clkmuxes = iobmux.clkmuxes(self.lines, self.entries)
        self.blocks = blocks.Blocks(self.entries)
        self.switch_pos = {g: name for name, g in switches.positions(self.lines).items()}
        self.mux_bits = {b for m in self.muxes.values() for b in m.bits.values()}
        self.mux_bits |= {b for i in self.iobs.values() for b in list(i.obits.values()) + list(i.tbits.values())}
        self.mux_bits |= {b for k in list(self.kmuxes.values()) + list(self.clkmuxes.values()) for b in k.bits.values()}
        bl = self.blocks
        self.block_bits = {b for t in bl.tiles for b in bl.clb_bitset[t]}
        self.block_bits |= {bl.bit("IOB %s.I PAD/Latched" % p) for p in bl.pads}
        self.block_bits |= {bl.bit("Other " + o) for o in bl.others}
        # names -> bit for encoding
        self.pip_bit = {self.lines.pip_name(e.key[0]): e.index for e in self.entries if e.kind == "pip"}
        self.switch_bit = {}
        for e in self.entries:
            if e.kind == "switch":
                g, p1, p2 = e.key
                self.switch_bit["%s %d-%d" % (self.switch_pos[g], min(p1, p2), max(p1, p2))] = e.index
        self.bidi_bit = {e.key[0]: e.index for e in self.entries if e.kind == "bidi"}


iob_source_name = iobmux.source_name  # name of a source of the O or T mux in the text format


def _none_value(m, c):
    """Value of a mux without a source: "none" for the default state (no bit programmed), otherwise none:<code>"""
    return "none" if c == (1 << len(m.bits)) - 1 else "none:%d" % c


def decode(db, raw):
    """(list of Item, list of problems). Problem: programmed NOT-USED bit, unknown mux code or a PIP whose lines
    are not known."""
    items, problems = [], []
    k_used = {}
    for name, m in sorted(db.muxes.items()):
        try:
            code, src = m.decode(raw)
        except KeyError:
            problems.append("%s: unknown mux code %d" % (name, m.code(raw)))
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
            problems.append("%s.O: unknown mux code %d" % (pin, c))
        c = iobmux.code(iob.tbits, raw)
        if c in iob.tmux:
            value = iob_source_name(iob.t[iob.tmux[c]])
        elif c in (iob.t_off, iob.t_on):
            value = "off" if c == iob.t_off else "on"
        else:
            problems.append("%s.T: unknown code %d" % (pin, c))
            continue
        items.append(Item("mux", pin + ".T", value, sorted(iob.tbits.values()), "Code %d" % c))
    for pin, km in sorted(db.kmuxes.items()):  # clock mux of the latched inputs of one side
        c = iobmux.code(km.bits, raw)
        if c in km.codes:
            items.append(Item("mux", pin + ".K", iob_source_name(km.sources[km.codes[c]]), sorted(km.bits.values()),
                              "Code %d, clock %s" % (c, {"T": "top", "R": "right", "B": "bottom", "L": "left"}[km.side])))
        else:
            problems.append("%s.K: unknown mux code %d" % (pin, c))
    for name, cm in sorted(db.clkmuxes.items()):  # inputs of the clock buffers GCLK and ACLK
        c = iobmux.code(cm.bits, raw)
        if c in cm.codes:
            items.append(Item("mux", name, iob_source_name(cm.sources[cm.codes[c]]), sorted(cm.bits.values()),
                              "Code %d, %s" % (c, cm.net)))
        else:
            problems.append("%s: unknown mux code %d" % (name, c))
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
            problems.append("Bit %d (frame %d, position %d) is programmed, but unused according to the bit map"
                            % (e.index, e.index // bitmap.FRAME_BITS, e.index % bitmap.FRAME_BITS))
        elif e.kind == "pip":
            name = db.lines.pip_name(e.key[0])
            if name is None:
                problems.append("PIP %s (bit %d): lines unknown" % (e.key[0], e.index))
                continue
            items.append(Item("pip", name, None, [e.index], e.key[0]))
        elif e.kind == "switch":
            g, p1, p2 = e.key
            items.append(Item("switch", db.switch_pos[g], "%d-%d" % tuple(sorted((p1, p2))), [e.index], None))
        elif e.kind == "bidi":  # programmed: the buffer drives down or right (graph._bidi)
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
    out = ["# XC2064 configuration as text (arch/xc2064/xc2064db/config.py)"]
    if source:
        out.append("# Source: %s" % source)
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
    """Lines of the text file as a list of Line (kind, name, value)"""
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
            raise ValueError("line %d: unknown kind %r" % (n, kind))
    return out


def encode(db, lines, defaults=True):
    """Lines -> raw (list of 0/1, 0 = programmed). defaults: first XACT's default state for everything the lines
    do not specify. Error (ValueError) on unknown names, sources and codes."""
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
            raise ValueError("line %d (%s %s %s): %s" % (l.lineno, l.kind, l.name, l.value, e))
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
                    raise ValueError("code %d is not a none code" % code)
            else:
                idx = [i for i, s in enumerate(m.sources) if s.line == l.value]
                codes = [c for c, i in m.codes.items() if idx and i == idx[0]]
                if not codes:
                    raise ValueError("no source %s" % l.value)
                code = codes[0]
            _set_code(raw, m.bits, code)
            return
        pin, _, which = l.name.partition(".")
        if which == "K" and pin in db.kmuxes:
            km = db.kmuxes[pin]
            found = [c for c, k in km.codes.items() if iob_source_name(km.sources[k]) == l.value]
            if not found:
                raise ValueError("no source %s" % l.value)
            _set_code(raw, km.bits, found[0])
            return
        if pin in db.iobs and which in ("O", "T"):
            iob = db.iobs[pin]
            if which == "T" and l.value in ("on", "off"):
                _set_code(raw, iob.tbits, iob.t_on if l.value == "on" else iob.t_off)
                return
            lst, codes, bits = (iob.o, iob.omux, iob.obits) if which == "O" else (iob.t, iob.tmux, iob.tbits)
            found = [c for c, k in codes.items() if iob_source_name(lst[k]) == l.value]
            if not found:
                raise ValueError("no source %s" % l.value)
            _set_code(raw, bits, found[0])
            return
        if l.name in db.clkmuxes:
            cm = db.clkmuxes[l.name]
            found = [c for c, k in cm.codes.items() if iob_source_name(cm.sources[k]) == l.value]
            if not found:
                raise ValueError("no source %s" % l.value)
            _set_code(raw, cm.bits, found[0])
            return
        raise ValueError("unknown mux")
    if l.kind == "pip":
        raw[db.pip_bit[l.name]] = 0
    elif l.kind == "switch":
        a, b = (int(v) for v in l.value.split("-"))
        raw[db.switch_bit["%s %d-%d" % (l.name, min(a, b), max(a, b))]] = 0
    elif l.kind == "bidi":
        if l.name == "auto":
            return
        if l.value not in ("down", "right", "up", "left"):
            raise ValueError("direction %r" % l.value)
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
