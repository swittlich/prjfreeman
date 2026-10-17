"""Netzliste aus einer Konfiguration (Bitstream): der Rückweg für den formalen Vergleich im Regressionstest.

Netze sind die Knoten des Routing-Graphen, die die programmierten Verbindungen zusammenschalten (Puffer an den
Sektionsgrenzen verbinden immer). Treiber sind X/Y der CLBs und die Eingänge der Pads (Pnn.I), Senken die
CLB-Eingänge und die Ausgangs- und T-Muxe der Pads. Aus jeder CLB entstehen die Zellen, die ihre Konfiguration
beschreibt (blocks.py): Funktionsgeneratoren als XC2000_LUT3 (F, G) bzw. XC2000_LUT4 (BASE F, B wählt),
das Speicherelement als XC2000_DFF, wenn sein Takt eingeschaltet ist. Pads werden IO-Puffer nach dem Modus
des T-Muxes (aus: INBUF, an: OUTBUF, sonst TOBUF bzw. IOBUF).

Der Bitstream kennt keine Namen: Ports (Pad -> Name, Richtung) und Register (CLB -> Name des Q-Netzes) kommen
aus den Zeilen "port" und "reg" der Textdatei, die nextpnr mit --vopt out= schreibt. Pads ohne Port bleiben
unbenutzt.
"""
import collections
import re

from . import blocks, config, graph as graph_mod

DEFAULT_IN = ["B", "C", "Q"]


def _find(parent, n):
    parent.setdefault(n, n)
    while parent[n] != n:
        parent[n] = parent[parent[n]]
        n = parent[n]
    return n


def build(db, raw, ports, regs, g=None):
    """Verilog-Text. ports: {Pin: (Name, Richtung)}, regs: {CLB: Name}. Fehler: ValueError."""
    g = g or graph_mod.Graph(db.entries, db.lines)
    items, problems = config.decode(db, raw)
    if problems:
        raise ValueError("; ".join(problems[:3]))
    clb = {it.name: blocks.parse_fields(it.value) for it in items if it.kind == "clb"}
    tmode = {it.name[:-2]: it.value for it in items if it.kind == "mux" and it.name.endswith(".T")}

    parent = {}
    for cn in g.conns:
        if graph_mod.conn_on(cn, raw):
            parent[_find(parent, cn.a)] = _find(parent, cn.b)
    root = lambda n: _find(parent, n)  # noqa: E731
    members = collections.defaultdict(list)
    for n in list(parent):
        members[root(n)].append(n)
    is_driver = lambda n: re.fullmatch(r"[A-H][A-H]\.[XY]|P\d+\.I", n)  # noqa: E731
    is_sink = lambda n: re.fullmatch(r"[A-H][A-H]\.[ABCDK]|P\d+\.[OT]", n)  # noqa: E731

    # Treiber je Netz; Name des Drahts = Name des Treibers
    wire_of = {}  # Knoten -> Drahtname (nur Netze mit Treiber)
    for r, nodes in members.items():
        drv = [n for n in nodes if is_driver(n)]
        if len(drv) > 1:
            raise ValueError("Netz mit zwei Treibern: %s" % ", ".join(sorted(drv)))
        if drv:
            for n in nodes:
                wire_of[n] = drv[0]
    has_sink = {r: any(is_sink(n) for n in nodes) for r, nodes in members.items()}
    used = lambda n: n in parent and has_sink[root(n)]  # noqa: E731

    cells, wires = [], set()
    names = {}  # Treiberknoten (AB.X, P9.I) -> Name im Verilog

    def net(node):
        """Draht an einem Eingangspin (CLB-Pin AB.A, Pad-Mux P9.O) oder None"""
        w = wire_of.get(node)
        if w is None:
            return None
        wires.add(w)
        return w

    port_name = {pin: name for pin, (name, _) in ports.items()}
    for t in sorted(clb):
        f = clb[t]
        base = f["BASE"]
        clk = f["CLK"].split(":") if f["CLK"] else []
        has_ff = bool(clk) and clk[0] in ("K", "C", "G")
        x_used, y_used = used(t + ".X"), used(t + ".Y")
        need = set()
        for o, u in (("X", x_used), ("Y", y_used)):
            if u and f[o] in ("F", "G"):
                need.add(f[o])
            elif u and f[o] == "UNDEF":
                raise ValueError("%s.%s: Ausgang UNDEF" % (t, o))
        if has_ff:
            need.add("F")
            if clk[0] == "G":
                need.add("G")
            if f["SET"] == "F":
                need.add("F")
            if f["RES"] == "G":
                need.add("G")
        if not need and not has_ff and not x_used and not y_used:
            continue
        q = regs.get(t, "%s.Q" % t)

        def pin(p):
            """Signal eines CLB-Eingangs A-D bzw. Q"""
            if p == "Q":
                return q if has_ff else None
            return net("%s.%s" % (t, p))

        out = {}
        if base == "F" and need:  # F und G als eine Funktion, B wählt (B = 1: Tabelle F)
            ins = f["F"].split(":") + ["B"]
            init = int(f["LUTF"], 16) << 8 | int(f["LUTG"], 16)
            o = "%s.FG" % t
            cells.append(("XC2000_LUT4", "%s.LUTFG" % t, {"INIT": "16'b{:016b}".format(init)},
                          {"I": [pin(p) for p in ins], "O": o}))
            out["F"] = out["G"] = o
        else:
            for lut in sorted(need):
                o = "%s.%s" % (t, lut)
                cells.append(("XC2000_LUT3", "%s.LUT%s" % (t, lut), {"INIT": "8'b{:08b}".format(int(f["LUT" + lut], 16))},
                              {"I": [pin(p) for p in f[lut].split(":")], "O": o}))
                out[lut] = o
            if base == "FGM" and need:  # B wählt zwischen F und G (M)
                raise ValueError("%s: BASE FGM wird nicht nachgebildet" % t)
        if has_ff:
            c = pin(clk[0]) if clk[0] in ("K", "C") else out["G"]
            conns = {"CLK": c, "D": out["F"], "Q": q}
            if f["SET"]:
                conns["S"] = pin("A") if f["SET"] == "A" else out["F"]
            if f["RES"]:
                conns["R"] = pin("D") if f["RES"] == "D" else out["G"]
            cells.append(("XC2000_DFF", "%s.FF" % t, {"LATCH": "1'b%d" % (f["Q"] == "LATCH"),
                                                       "CLKINV": "1'b%d" % ("NOT" in clk)}, conns))
            wires.add(q)
        for o in ("X", "Y"):
            src = {"Q": q if has_ff else None, "F": out.get("F"), "G": out.get("G")}.get(f[o])
            if (x_used if o == "X" else y_used) and src:
                names["%s.%s" % (t, o)] = src
        for v in out.values():
            wires.add(v)

    # IO-Puffer an den Pads mit Port
    for pin, (name, d) in sorted(ports.items(), key=lambda kv: int(kv[0][1:])):
        mode = tmode.get(pin, "off")
        if mode == "off":
            cells.append(("XC2000_INBUF", pin + ".BUF", {}, {"PAD": ("port", name), "O": pin + ".I"}))
        elif mode == "on":
            cells.append(("XC2000_OUTBUF", pin + ".BUF", {}, {"I": net(pin + ".O"), "PAD": ("port", name)}))
        else:
            conns = {"I": net(pin + ".O"), "T": net(pin + ".T"), "PAD": ("port", name)}
            if used(pin + ".I") or d == "inout":
                cells.append(("XC2000_IOBUF", pin + ".BUF", {}, dict(conns, O=pin + ".I")))
            else:
                cells.append(("XC2000_TOBUF", pin + ".BUF", {}, conns))
        if mode != "on":
            wires.add(pin + ".I")

    # Verilog: Drähte heißen wie ihr Treiber (bzw. dessen Name aus port/reg)
    esc = lambda s: "\\" + s + " "  # noqa: E731
    rename = lambda w: names.get(w, w)  # noqa: E731
    vec = re.compile(r"^(.*)\[(\d+)\]$")
    groups = {}
    for pin, (name, d) in ports.items():
        m = vec.match(name)
        base, idx = (m.group(1), int(m.group(2))) if m else (name, None)
        groups.setdefault(base, [d, []])[1].append(idx)

    def port_ref(name):
        m = vec.match(name)
        return "%s[%s]" % (esc(m.group(1)), m.group(2)) if m and m.group(1) in groups else esc(name)

    undriven = [0]

    def ref(sig):
        if isinstance(sig, tuple):
            return port_ref(sig[1])
        if sig is None:
            undriven[0] += 1
            wires.add("$undriven%d" % undriven[0])
            return esc("$undriven%d" % undriven[0])
        return esc(rename(sig))

    lines = []
    for typ, inst, params, conns in cells:
        parts = []
        for p, s in conns.items():
            if isinstance(s, list):  # Bus I[0..n], höchstes Bit zuerst
                parts.append(".%s({%s})" % (p, ", ".join(ref(x) for x in reversed(s))))
            else:
                parts.append(".%s(%s)" % (p, ref(s)))
        prm = ", ".join(".%s(%s)" % kv for kv in params.items())
        lines.append("\t%s %s%s (%s);" % (typ, "#(%s) " % prm if prm else "", esc(inst), ", ".join(parts)))
    out = ["// aus dem Bitstream zurückgewonnen (arch/xc2064/xc2064db/netlist.py)",
           "module top (%s);" % ", ".join(esc(b) for b in sorted(groups))]
    for base, (d, idx) in sorted(groups.items()):
        rng = "[%d:%d] " % (max(idx), min(idx)) if idx[0] is not None else ""
        out.append("\t%s %s%s;" % (d, rng, esc(base)))
    port_names = set(port_name.values())
    for w in sorted({rename(w) for w in wires} - port_names):
        out.append("\twire %s;" % esc(w))
    return "\n".join(out + lines) + "\nendmodule\n"


def read_meta(text):
    """Zeilen port/reg aus der Textdatei von nextpnr: (ports, regs)"""
    ports, regs = {}, {}
    for l in config.parse_text(text):
        if l.kind == "port":
            name, _, d = l.value.rpartition(" ")
            ports[l.name] = (name, d)
        elif l.kind == "reg":
            regs[l.name] = l.value
    return ports, regs
