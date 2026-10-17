"""TEST1.LCA (XACT 5.1.0) als Gegenprobe für TEST1.RBT: XACT listet je Netz die Pins (Addnet) und alle
programmierten Elemente (NProgram) mit eigenen Namen, je Block (Editblk) Base, Config und die Gleichungen
der Funktionsgeneratoren (Equate). Daraus drei Prüfungen:

  elements()  jedes Element von XACT muss in der Dekodierung von TEST1.RBT stehen (Namen und Bitkarte)
  nets()      der Routing-Graph muss die CLB-Pins jedes Netzes verbinden und verschiedene Netze trennen
  blocks()    Config und Equate jedes Blocks müssen zur Dekodierung passen (blocks.py)

Namen bei XACT: "BD.8.2.0 BD.8.2.4" ist eine Verbindung der Switch-Matrix BD.8.2 (Pins ab 0, hier ab 1),
"col.D.local.3:AD.B" die Quelle des CLB-Eingangs AD.B, "col.D.local.4:BC.X" ein Ausgangs-Pip,
"col.B.local.5:row.B.local.3-s" ein PIP (Zusatz -s/-l ohne Bedeutung für das Bit), "...:PAD17.T" ein IOB.
"""
import collections
import re

from . import sources
from .graph import conn_on


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
        if a.startswith("PAD"):
            a, b = b, a
        if b.startswith("PAD"):
            out.append(("iob", "%s %s" % (b, a)))
        elif re.fullmatch(r"[A-H][A-H]\.[ABCDK]", b):
            out.append(("mux", "%s %s" % (b, a)))
        elif re.fullmatch(r"[A-H][A-H]\.[XY]", b):
            out.append(("out", "%s %s" % (b, a)))
        else:
            out.append(("pip", "%s:%s" % (a, b)))
        i += 1
    return out


def check_elements(nets, items, db):
    """Elemente von XACT, die in der Dekodierung (config.decode) fehlen: {Art: [Name, ...]}, dazu Zähler.
    IOB-Elemente "LINE:PADn.O/T" sind Mux-Quellen, "LINE:PADn.I" Eingangs-Pips (Lage aus iob.js);
    Takte der gelatchten IOBs (.K und die Kreuzungen ihrer Muxe, ohne PIP-Bit) zählen unter "iob-k"."""
    have = set()
    for it in items:
        if it.kind == "switch":
            have.add(("switch", "%s %s" % (it.name, it.value)))
        elif it.kind == "pip":
            have.add(("pip", it.name))
        elif it.kind == "mux":
            have.add(("mux", "%s %s" % (it.name, it.value)))
    pin_of = {iob.pad: pin for pin, iob in db.iobs.items()}
    pip_names = {db.lines.pip_name(e.key[0]) for e in db.entries if e.kind == "pip"}
    # Puffer aus bzw. immer an: die T-Bits tragen den Modus, eine geroutete Leitung am T-Eingang wählt der
    # Mux dann nicht (in TEST1 z. B. P8 "BUF:" mit Netz an P8.T)
    t_mode = {it.name: it.value for it in items if it.kind == "mux" and it.name.endswith(".T")}
    for p, v in t_mode.items():
        if v in ("off", "on"):
            have.add(("mux-mode", p))
    missing, count = collections.defaultdict(list), collections.Counter()
    for net in nets.values():
        for kind, name in classify(net["elements"]):
            if kind == "iob":
                pad, line = name.split()
                padname, which = pad.split(".")
                pin = pin_of[padname]
                if which == "K":
                    kind = "iob-k"
                elif which == "T" and ("mux-mode", pin + ".T") in have:
                    kind, name = "mux-mode", pin + ".T"
                elif which in "OT":
                    kind, name = "mux", "%s.%s %s" % (pin, which, line)
                else:
                    ent = [e for e in db.iobs[pin].i if e.kind == "route" and e.line == line]
                    kind, name = "pip", db.lines.pip_name(ent[0].g) if ent else "%s.I %s" % (pin, line)
            if kind == "out":  # X -> Zeile io6, Y -> Zeile y der CLB
                clb, line = name.split()
                row = "row.%s.%s" % (clb[0], "io6" if clb.endswith(".X") else "y")
                kind, name = "pip", "%s:%s" % (line, row)
            if kind == "pip" and name not in pip_names:
                kind = "iob-k"  # Kreuzung ohne PIP-Bit: Quelle eines K-Mux (Takt gelatchter IOBs)
            count[kind] += 1
            if kind != "iob-k" and (kind, name) not in have:
                missing[kind].append(name)
    return missing, count


def check_nets(nets, graph, raw, skip=()):
    """Verbindet der Graph mit den programmierten Bits die CLB- und IOB-Pins jedes Netzes, und nur diese?
    skip: Pins, die nicht zählen (T-Eingänge mit Puffer aus/an). Ergebnis: Liste (Netz, Pins, Zustand) mit
    Zustand ok, getrennt (Pins in mehreren Teilen) oder verbunden mit (Pins eines anderen Netzes im selben Teil)."""
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
        if conn_on(cn, raw):
            union(cn.a, cn.b)
    owner, result = {}, []
    for name, net in nets.items():
        pins = [p for p in net["pins"] if re.fullmatch(r"[A-H][A-H]\.[ABCDKXY]|P\d+\.[IOT]", p) and p not in skip]
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


def parse_blocks(path=None):
    """{Block: {"base": ..., "config": {Feld: Wert}, "equate": [(F/G, Gleichung)]}} (CLBs und IOBs)"""
    text = sources.read_text(path or sources.TEST1_RBT.replace(".RBT", ".LCA"))
    out = {}
    for name, body in re.findall(r"Editblk (\S+)\n(.*?)Endblk", text, re.S):
        cfg = re.search(r"Config (.*)", body)
        out[name] = {"base": (re.findall(r"Base (\S+)", body) or [""])[-1],
                     "config": {k: v for k, _, v in (t.partition(":") for t in cfg.group(1).split())} if cfg else {},
                     "equate": re.findall(r"Equate (\w) = (.*)", body)}
    return out


def _eval(eq, env):
    py = eq.replace("~", " not ").replace("*", " and ").replace("+", " or ").replace("@", " ^ ")
    return int(bool(eval(py, {"__builtins__": {}}, dict(env))))


def check_blocks(lca_blocks, items):
    """Abweichungen der dekodierten Blöcke (Items clb/iob/mux aus config.decode) von Config und Equate:
    Liste (Block, Text). Leere Felder bei XACT (unbenutzt) zählen nicht; XACT nennt bei F/G nur die
    benutzten Eingänge, die müssen unter den gewählten sein."""
    from . import blocks as blocks_mod
    clb = {it.name: blocks_mod.parse_fields(it.value) for it in items if it.kind == "clb"}
    iob = {it.name: blocks_mod.parse_fields(it.value) for it in items if it.kind == "iob"}
    tmux = {it.name[:-2]: it.value for it in items if it.kind == "mux" and it.name.endswith(".T")}
    bad = []
    for name, b in lca_blocks.items():
        if b["base"] == "IO":
            pin = "P%d" % int(name[1:]) if re.fullmatch(r"P\d+", name) else name
            got = {"I": iob[pin]["I"], "BUF": {"on": "ON", "off": ""}.get(tmux[pin], "TRI")}
            for k, v in b["config"].items():
                if v and got.get(k) != v:
                    bad.append((name, "%s:%s, dekodiert %s" % (k, v, got.get(k))))
            continue
        f = clb[name]
        if b["base"] != f["BASE"]:
            bad.append((name, "Base %s, dekodiert %s" % (b["base"], f["BASE"])))
        for k in ("X", "Y", "Q", "SET", "RES", "CLK"):
            v = b["config"].get(k, "")
            if (v or k in ("SET", "RES", "CLK")) and v != f[k]:
                bad.append((name, "%s:%s, dekodiert %s" % (k, v, f[k])))
        for lut, eq in b["equate"]:
            ins = f[lut].split(":")
            table = int(f["LUT" + lut], 16)
            if f["BASE"] == "F":  # 4 Variablen, B = 1: Tabelle F
                table, ins = int(f["LUTF"], 16) << 8 | int(f["LUTG"], 16), ins + ["B"]
            for i in range(1 << len(ins)):
                vals = [(v, (i >> k) & 1) for k, v in enumerate(ins)]
                if any(a == c and x != y for a, x in vals for c, y in vals):
                    continue  # derselbe Eingang zweimal: Kombination kommt nicht vor
                env = dict({v: 0 for v in "ABCDQ"}, **dict(vals))
                if _eval(eq, env) != (table >> i) & 1:
                    bad.append((name, "%s = %s stimmt nicht mit LUT%s %s (%s)" % (lut, eq, lut, f["LUT" + lut], f[lut])))
                    break
    return bad
