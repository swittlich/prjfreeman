"""TEST1.LCA (XACT 5.1.0) als Gegenprobe für TEST1.RBT: XACT listet je Netz die Pins (Addnet) und alle
programmierten Elemente (NProgram) mit eigenen Namen. Daraus zwei Prüfungen:

  elements()  jedes Element von XACT muss in der Dekodierung von TEST1.RBT stehen (Namen und Bitkarte)
  nets()      der Routing-Graph muss die CLB-Pins jedes Netzes verbinden und verschiedene Netze trennen

Namen bei XACT: "BD.8.2.0 BD.8.2.4" ist eine Verbindung der Switch-Matrix BD.8.2 (Pins ab 0, hier ab 1),
"col.D.local.3:AD.B" die Quelle des CLB-Eingangs AD.B, "col.D.local.4:BC.X" ein Ausgangs-Pip,
"col.B.local.5:row.B.local.3-s" ein PIP (Zusatz -s/-l ohne Bedeutung für das Bit), "...:PAD17.T" ein IOB.
"""
import collections
import re

from . import sources


def parse(path=None):
    """{Netz: {"pins": [...], "elements": [...]}} in Dateireihenfolge"""
    nets = collections.OrderedDict()
    for line in sources.read_text(path or sources.TEST1_RBT.replace(".RBT", ".LCA")).splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == "Addnet":
            nets.setdefault(w[1], {"pins": [], "elements": []})["pins"] += w[2:]
        elif w[0] == "NProgram":
            nets.setdefault(w[1], {"pins": [], "elements": []})["elements"] += w[2:]
    return nets


def classify(elements):
    """Elemente eines Netzes -> Liste (Art, Name) mit Art switch, pip, mux, out, iob"""
    out, i = [], 0
    while i < len(elements):
        e = elements[i]
        m = re.fullmatch(r"([A-I][A-I]\.8\.[12])\.([0-7])", e)
        if m:
            m2 = re.fullmatch(r"([A-I][A-I]\.8\.[12])\.([0-7])", elements[i + 1])
            assert m2 and m2[1] == m[1], "Switch-Pins nicht paarweise: %s %s" % (e, elements[i + 1])
            p = sorted((int(m[2]) + 1, int(m2[2]) + 1))
            out.append(("switch", "%s %d-%d" % (m[1], p[0], p[1])))
            i += 2
            continue
        a, b = e.split(":", 1)
        b = re.sub(r"-[sl]$", "", b)
        if b.startswith("PAD") or a.startswith("PAD"):
            out.append(("iob", e))
        elif re.fullmatch(r"[A-H][A-H]\.[ABCDK]", b):
            out.append(("mux", "%s %s" % (b, a)))
        elif re.fullmatch(r"[A-H][A-H]\.[XY]", b):
            out.append(("out", "%s %s" % (b, a)))
        else:
            out.append(("pip", "%s:%s" % (a, b)))
        i += 1
    return out


def check_elements(nets, items):
    """Elemente von XACT, die in der Dekodierung (config.decode) fehlen: {Art: [Name, ...]}, dazu Zähler"""
    have = set()
    for it in items:
        if it.kind == "switch":
            have.add(("switch", "%s %s" % (it.name, it.value)))
        elif it.kind == "pip":
            have.add(("pip", it.name))
        elif it.kind == "mux":
            have.add(("mux", "%s %s" % (it.name, it.value)))
    missing, count = collections.defaultdict(list), collections.Counter()
    for net in nets.values():
        for kind, name in classify(net["elements"]):
            count[kind] += 1
            if kind == "iob":
                continue
            if kind == "out":  # X -> Zeile io6, Y -> Zeile y der CLB
                clb, line = name.split()
                row = "row.%s.%s" % (clb[0], "io6" if clb.endswith(".X") else "y")
                kind, name = "pip", "%s:%s" % (line, row)
            if (kind, name) not in have:
                missing[kind].append(name)
    return missing, count


def check_nets(nets, graph, raw):
    """Verbindet der Graph mit den programmierten Bits die CLB-Pins jedes Netzes, und nur diese?
    Ergebnis: Liste (Netz, CLB-Pins, Zustand) mit Zustand ok, getrennt (Pins in mehreren Teilen) oder
    verbunden mit (Pins eines anderen Netzes im selben Teil)."""
    parent = {}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a, b):
        parent[find(a)] = find(b)

    for cn in graph.conns:
        if cn.kind == "mux":
            if sum(raw[b] << n for n, b in enumerate(cn.bits)) == cn.code:
                union(cn.a, cn.b)
        elif all(raw[b] == 0 for b in cn.bits):
            union(cn.a, cn.b)
    owner, result = {}, []
    for name, net in nets.items():
        pins = [p for p in net["pins"] if re.fullmatch(r"[A-H][A-H]\.[ABCDKXY]", p)]
        for p in pins:
            owner.setdefault(find(p), name)
        result.append([name, pins, None])
    for r in result:
        parts = {find(p) for p in r[1]}
        if len(parts) > 1:
            r[2] = "getrennt"
        elif parts:
            other = owner[next(iter(parts))]
            r[2] = "ok" if other == r[0] else "verbunden mit %s" % other
        else:
            r[2] = "ohne CLB-Pins"
    return result
