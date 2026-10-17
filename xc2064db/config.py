"""Konfiguration als lesbare Textdatei (das Format zwischen nextpnr und xc2064pack, Rückweg xc2064unpack).

Eine Zeile je Eintrag, Namen wie bei Shirriff, '#' leitet einen Kommentar ein:

    device XC2064
    mux AB.A row.A.local.1          CLB-Eingang A..D, K und die gewählte Quellleitung (oder none)
    mux P59.O col.I.local.4         Ausgangs-Mux eines IOB (Leitung, X/Y einer CLB wie AH.X, GCLK)
    mux P59.T col.I.long.2          Tristate-Mux eines IOB: Quelle (Tristate), on (immer aktiv) oder off
    pip col.B.local.1:row.C.local.3 einzelnes PIP-Bit, Kreuzung einer col- mit einer row-Leitung
    switch BC.8.1 1-3               Verbindung zweier Pins einer Switch-Matrix (Magic-Bit)
    bidi 125G6 right                Repowering-Puffer (Name = Lage bei Shirriff) und seine Richtung: down/right
                                    (Bit programmiert) oder up/left (Grundzustand, nicht aufgeführt)
    bit CLB AB Logic Table: 2 Bit: 0
                                    jedes andere programmierte Bit mit seinem Namen aus XC2064-def.txt
                                    (LUT, FF, X/Y, IOB-Muxe und -Optionen, Taktpuffer, Other)

Dekodiert sind die CLB-Eingänge, die O- und T-Muxe der IOBs (mit Modus), Pips, Switch-Matrizen und die
Richtung der Repowering-Puffer (Bidi-Bits); alles Weitere steht bitweise da und wird in den folgenden Stufen zu Bel-Optionen (z. B. LUT-Inhalt). Die Datei ist
verlustfrei: Aus ihr ergibt sich jedes programmierte Bit, die Mux-Bits über die Codes.
"""
import collections

from . import bitmap, clbmux, iobmux, lines as lines_mod, switches

Item = collections.namedtuple("Item", "kind name value bits comment")


class Database:
    """Alles, was die Dekodierung braucht, einmal geladen"""

    def __init__(self):
        self.entries = bitmap.load()
        self.lines = lines_mod.Lines()
        self.muxes = clbmux.muxes(self.lines, self.entries)
        self.iobs = iobmux.iobs(self.lines, self.entries)
        self.switch_pos = {g: name for name, g in switches.positions(self.lines).items()}
        self.mux_bits = {b for m in self.muxes.values() for b in m.bits.values()}
        self.mux_bits |= {b for i in self.iobs.values() for b in list(i.obits.values()) + list(i.tbits.values())}


def iob_source_name(ent):
    """Name einer Quelle des O- bzw. T-Mux im Textformat: Leitung, X/Y einer CLB oder GCLK"""
    if ent.kind == "route":
        return ent.line
    if ent.kind in ("x", "y"):
        return "%s.%s" % (ent.special, ent.kind.upper())
    return ent.kind.upper()


def decode(db, raw):
    """(Liste von Item, Liste von Problemen). Problem: programmiertes NOT-USED-Bit, unbekannter Mux-Code
    oder ein PIP, dessen Leitungen nicht bekannt sind."""
    items, problems = [], []
    for name, m in sorted(db.muxes.items()):
        try:
            code, src = m.decode(raw)
        except KeyError:
            problems.append("%s: unbekannter Mux-Code %d" % (name, m.code(raw)))
            continue
        items.append(Item("mux", name, src.line if src else "none", sorted(m.bits.values()), "Code %d" % code))
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
    for e in db.entries:
        if raw[e.index] != 0 or e.index in db.mux_bits:
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


def format_text(items, source=None):
    out = ["# XC2064-Konfiguration als Text (arch/xc2064/xc2064db/config.py)"]
    if source:
        out.append("# Quelle: %s" % source)
    out.append("device XC2064")
    order = {"mux": 0, "pip": 1, "switch": 2, "bidi": 3, "bit": 4}
    for it in sorted(items, key=lambda it: (order[it.kind], it.name, it.value or "")):
        line = "%s %s" % (it.kind, it.name) + (" %s" % it.value if it.value else "")
        if it.comment:
            line = "%-44s # %s" % (line, it.comment)
        out.append(line)
    return "\n".join(out) + "\n"
