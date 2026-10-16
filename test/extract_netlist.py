# nextpnr --post-route: Netzliste allein aus den belegten Bels und den benutzten Pips zurückgewinnen,
# also aus dem, was ein Bitstream festhält. Von jedem Bel-Ausgang aus folgt das Skript den benutzten
# Pips bis zu den Bel-Eingängen, die es erreicht. Namen (Netze, Ports) und Zellparameter kommen aus der
# Netzliste, die Verbindungen nur aus dem Routing.
#
# Prüft: jeder Eingang hat höchstens einen Treiber, jeder erreichte Eingang gehört zum Netz seines
# Treibers in der Netzliste und umgekehrt, und jeder benutzte Pip liegt auf einem solchen Weg.
# Schreibt die Netzliste als Verilog nach $XC2064_EXTRACT (für den Äquivalenzvergleich in run.sh)
# und eine Zeile "XC2064_EXTRACT: ..." ins Log.
import os
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nextpnr_api import ctx

out_file = os.environ["XC2064_EXTRACT"]
errors = []

cells = {name: c for name, c in ctx.cells}
ports_of = {name: {k: p for k, p in c.ports} for name, c in cells.items()}
cell_at = {c.bel: c for c in cells.values() if c.bel}
is_out = lambda p: str(p.type).endswith("PORT_OUT")
# IO-Puffer: Richtung des Top-Level-Ports an PAD. PAD hängt am Pin, nicht am Routing.
IO_DIR = {"XC2000_INBUF": "input", "XC2000_OUTBUF": "output", "XC2000_TOBUF": "output", "XC2000_IOBUF": "inout"}
is_pad = lambda c, port: port == "PAD" and c.type in IO_DIR


def reach(wire):
    """Drähte, die von wire aus über benutzte Pips erreichbar sind, und die Pips dorthin"""
    seen, pips, todo = {wire}, set(), [wire]
    while todo:
        w = todo.pop()
        for pip in ctx.getPipsDownhill(w):
            if ctx.getBoundPipNet(pip) is None:
                continue
            pips.add(pip)
            dst = ctx.getPipDstWire(pip)
            if dst not in seen:
                seen.add(dst)
                todo.append(dst)
    return seen, pips


# Treiber (Zelle, Port) je Eingang (Zelle, Port), nur aus dem Routing
driver_of = {}
reached_pips = set()
for c in cells.values():
    for port, pi in c.ports:
        if not is_out(pi) or is_pad(c, port):
            continue
        wires, pips = reach(ctx.getBelPinWire(c.bel, port))
        reached_pips |= pips
        for w in wires:
            for bp in ctx.getWireBelPins(w):
                sink = cell_at.get(bp.bel)
                if sink is None or (sink.name, bp.pin) == (c.name, port):
                    continue
                sp = ports_of[sink.name].get(bp.pin)
                if sp is not None and is_out(sp):
                    continue
                key = (sink.name, bp.pin)
                if key in driver_of and driver_of[key] != (c.name, port):
                    errors.append("%s.%s: zwei Treiber, %s.%s und %s.%s" % (key + driver_of[key] + (c.name, port)))
                driver_of[key] = (c.name, port)

# Vergleich mit der Netzliste
for c in cells.values():
    for port, pi in c.ports:
        if is_out(pi) or is_pad(c, port):
            continue
        key = (c.name, port)
        want = (pi.net.driver.cell.name, pi.net.driver.port) if pi.net and pi.net.driver.cell else None
        got = driver_of.get(key)
        if got != want:
            errors.append("%s.%s: Routing verbindet %s, Netzliste %s" % (c.name, port, got, want))
for key in driver_of:
    pi = ports_of[key[0]].get(key[1])
    if pi is None:
        errors.append("%s.%s: im Routing getrieben, aber kein Port der Zelle" % key)

bound_pips = [p for p in ctx.getPips() if ctx.getBoundPipNet(p) is not None]
for pip in bound_pips:
    if pip not in reached_pips:
        errors.append("Pip %s (Netz %s) liegt auf keinem Weg von einem Bel-Ausgang"
                      % (pip, ctx.getBoundPipNet(pip).name))

# --- Verilog ------------------------------------------------------------------------------------
esc = lambda s: "\\" + s + " "
vec = re.compile(r"^(.*)\[(\d+)\]$")


def net_name(drv):
    pi = ports_of[drv[0]][drv[1]]
    return pi.net.name if pi.net else "%s.%s" % drv


def param(v):
    s = str(v)
    return "%d'b%s" % (len(s), s) if re.fullmatch(r"[01xz]+", s) else '"%s"' % s


top_ports = {}  # Port-Name -> Richtung, aus den PAD-Netzen der IO-Puffer
for c in cells.values():
    if c.type in IO_DIR:
        top_ports[ports_of[c.name]["PAD"].net.name] = IO_DIR[c.type]
groups = {}
for name, d in top_ports.items():
    m = vec.match(name)
    base, idx = (m.group(1), int(m.group(2))) if m else (name, None)
    groups.setdefault(base, [d, []])[1].append(idx)


def port_ref(name):
    m = vec.match(name)
    return "%s[%s]" % (esc(m.group(1)), m.group(2)) if m and m.group(1) in groups else esc(name)


lines, wires, undriven = [], set(), 0
for c in sorted(cells.values(), key=lambda c: c.name):
    conns = {}
    for port, pi in c.ports:
        if is_pad(c, port):
            conns[port] = port_ref(pi.net.name)
        elif is_out(pi):
            n = net_name((c.name, port))
            wires.add(n)
            conns[port] = esc(n)
        elif (c.name, port) in driver_of:
            n = net_name(driver_of[(c.name, port)])
            wires.add(n)
            conns[port] = esc(n)
    # Busse (I[0], I[1], ...) wieder zusammenfassen, offene Bits als eigene, ungetriebene Drähte
    buses = {}
    for port in list(conns):
        m = vec.match(port)
        if m:
            buses.setdefault(m.group(1), {})[int(m.group(2))] = conns.pop(port)
    for base, bits in buses.items():
        parts = []
        for i in range(max(bits), -1, -1):
            if i not in bits:
                undriven += 1
                bits[i] = esc("$undriven%d" % undriven)
                wires.add("$undriven%d" % undriven)
            parts.append(bits[i])
        conns[base] = "{" + ", ".join(parts) + "}"
    params = ", ".join(".%s(%s)" % (k, param(v)) for k, v in c.params)
    lines.append("\t%s %s%s (%s);" % (c.type, "#(%s) " % params if params else "", esc(c.name),
                                      ", ".join(".%s(%s)" % (k, v) for k, v in sorted(conns.items()))))

with open(out_file, "w") as f:
    f.write("// aus Bels und benutzten Pips zurückgewonnen (arch/xc2064/test/extract_netlist.py)\n")
    f.write("module top (%s);\n" % ", ".join(esc(b) for b in sorted(groups)))
    for base, (d, idx) in sorted(groups.items()):
        rng = "[%d:%d] " % (max(idx), min(idx)) if idx[0] is not None else ""
        f.write("\t%s %s%s;\n" % (d, rng, esc(base)))
    for w in sorted(wires - set(top_ports)):
        f.write("\twire %s;\n" % esc(w))
    f.write("\n".join(lines) + "\nendmodule\n")

for e in errors[:20]:
    print("XC2064_EXTRACT Fehler: " + e)
print("XC2064_EXTRACT: %d Eingänge verbunden, %d Pips, %d Fehler" % (len(driver_of), len(bound_pips), len(errors)))
sys.stdout.flush()
