# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
"""Netlist from a configuration (bitstream): the way back for the formal comparison in the regression test.

Nets are the nodes of the routing graph that the programmed connections tie together (buffers at the section
boundaries always connect). Drivers are X/Y of the CLBs and the inputs of the pads (Pnn.I), sinks are the CLB
inputs and the output and T muxes of the pads. Each CLB yields the cells that its configuration describes
(blocks.py): function generators as XC2000_LUT3 (F, G), XC2000_LUT4 (BASE F, B selects) or XC2000_FGM (BASE
FGM, B selects between F and G with their own inputs), the storage element as XC2000_DFF if its clock is
enabled. Pads become IO buffers according to the mode of the T mux (off: INBUF, on: OUTBUF, otherwise TOBUF or
IOBUF), a latched input (I:Q) becomes XC2000_INFF with the clock of the line of its side.

The bitstream knows no names: ports (pad -> name, direction) and registers (CLB or pad with a latched input ->
name of the Q net) come from the lines "port" and "reg" of the text file that nextpnr writes with --vopt out=.
Pads without a port remain unused.
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
    """Verilog text. ports: {pin: (name, direction)}, regs: {CLB or pin: name}. Errors: ValueError."""
    g = g or graph_mod.Graph(db.entries, db.lines)
    items, problems = config.decode(db, raw)
    if problems:
        raise ValueError("; ".join(problems[:3]))
    clb = {it.name: blocks.parse_fields(it.value) for it in items if it.kind == "clb"}
    iob = {it.name: blocks.parse_fields(it.value) for it in items if it.kind == "iob"}
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
    latched = lambda p: iob[p]["I"] == "Q"  # noqa: E731
    is_sink = lambda n: (re.fullmatch(r"[A-H][A-H]\.[ABCDK]|P\d+\.[OT]", n)  # noqa: E731
                         or (re.fullmatch(r"P\d+\.K", n) and latched(n[:-2])))

    # driver per net; name of the wire = name of the driver
    wire_of = {}  # node -> wire name (only nets with a driver)
    for r, nodes in members.items():
        drv = [n for n in nodes if is_driver(n)]
        if len(drv) > 1:
            raise ValueError("net with two drivers: %s" % ", ".join(sorted(drv)))
        if drv:
            for n in nodes:
                wire_of[n] = drv[0]
    has_sink = {r: any(is_sink(n) for n in nodes) for r, nodes in members.items()}
    used = lambda n: n in parent and has_sink[root(n)]  # noqa: E731

    cells, wires = [], set()
    names = {}  # driver node (AB.X, P9.I) -> name in the Verilog

    def net(node):
        """Wire at an input pin (CLB pin AB.A, pad mux P9.O) or None"""
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
                raise ValueError("%s.%s: output UNDEF" % (t, o))
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
            """Signal of a CLB input A-D or Q"""
            if p == "Q":
                return q if has_ff else None
            return net("%s.%s" % (t, p))

        out = {}
        if base == "F" and need:  # F and G as one function, B selects (B = 1: table F)
            ins = f["F"].split(":") + ["B"]
            init = int(f["LUTF"], 16) << 8 | int(f["LUTG"], 16)
            o = "%s.FG" % t
            cells.append(("XC2000_LUT4", "%s.LUTFG" % t, {"INIT": "16'b{:016b}".format(init)},
                          {"I": [pin(p) for p in ins], "O": o}))
            out["F"] = out["G"] = o
        elif base == "FGM" and need:  # mux mode: F and G with their own inputs, B selects (B = 1: F), output M
            o = "%s.M" % t
            cells.append(("XC2000_FGM", "%s.FGM" % t, {"INIT_F": "8'b{:08b}".format(int(f["LUTF"], 16)),
                                                       "INIT_G": "8'b{:08b}".format(int(f["LUTG"], 16))},
                          {"F": [pin(p) for p in f["F"].split(":")], "G": [pin(p) for p in f["G"].split(":")],
                           "S": pin("B"), "O": o}))
            out["F"] = out["G"] = o
        else:
            for lut in sorted(need):
                o = "%s.%s" % (t, lut)
                cells.append(("XC2000_LUT3", "%s.LUT%s" % (t, lut), {"INIT": "8'b{:08b}".format(int(f["LUT" + lut], 16))},
                              {"I": [pin(p) for p in f[lut].split(":")], "O": o}))
                out[lut] = o
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

    # IO buffers at the pads with a port
    for pin, (name, d) in sorted(ports.items(), key=lambda kv: int(kv[0][1:])):
        mode = tmode.get(pin, "off")
        if latched(pin) and mode != "off":
            raise ValueError("%s: latched input with output driver is not modelled" % pin)
        if latched(pin):  # FF in the IOB, clock from the line of the side (K mux)
            cells.append(("XC2000_INFF", pin + ".BUF", {}, {"PAD": ("port", name), "K": net(pin + ".K"),
                                                             "O": pin + ".I"}))
            if pin in regs:
                names[pin + ".I"] = regs[pin]
        elif mode == "off":
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

    # Verilog: wires are named after their driver (or its name from port/reg)
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
            if isinstance(s, list):  # bus I[0..n], highest bit first
                parts.append(".%s({%s})" % (p, ", ".join(ref(x) for x in reversed(s))))
            else:
                parts.append(".%s(%s)" % (p, ref(s)))
        prm = ", ".join(".%s(%s)" % kv for kv in params.items())
        lines.append("\t%s %s%s (%s);" % (typ, "#(%s) " % prm if prm else "", esc(inst), ", ".join(parts)))
    out = ["// recovered from the bitstream (arch/xc2064/xc2064db/netlist.py)",
           "module top (%s);" % ", ".join(esc(b) for b in sorted(groups))]
    for base, (d, idx) in sorted(groups.items()):
        rng = "[%d:%d] " % (max(idx), min(idx)) if idx[0] is not None else ""
        out.append("\t%s %s%s;" % (d, rng, esc(base)))
    port_names = set(port_name.values())
    for w in sorted({rename(w) for w in wires} - port_names):
        out.append("\twire %s;" % esc(w))
    return "\n".join(out + lines) + "\nendmodule\n"


def read_meta(text):
    """Lines port/reg from nextpnr's text file: (ports, regs)"""
    ports, regs = {}, {}
    for l in config.parse_text(text):
        if l.kind == "port":
            name, _, d = l.value.rpartition(" ")
            ports[l.name] = (name, d)
        elif l.kind == "reg":
            regs[l.name] = l.value
    return ports, regs
