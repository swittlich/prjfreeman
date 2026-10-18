# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""TEST1.LCA (XACT 5.1.0) as a cross-check for TEST1.RBT: per net, XACT lists the pins (Addnet) and all
programmed elements (NProgram) under its own names, per block (Editblk) Base, Config and the equations
of the function generators (Equate). From this, three checks:

  elements()  every element from XACT must appear in the decoding of TEST1.RBT (names and bit map)
  nets()      the routing graph must connect the CLB pins of each net and keep different nets separate
  blocks()    Config and Equate of each block must match the decoding (blocks.py)

Names in XACT: "BD.8.2.0 BD.8.2.4" is a connection of the switch matrix BD.8.2 (pins from 0, here from 1),
"col.D.local.3:AD.B" the source of the CLB input AD.B, "col.D.local.4:BC.X" an output pip,
"col.B.local.5:row.B.local.3-s" a PIP (suffix -s/-l irrelevant for the bit), "...:PAD17.T" an IOB.
"""
import collections
import re

from . import sources
from .graph import conn_on


def parse(path=None):
    """{net: {"pins": [...], "elements": [...]}} in file order"""
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
    """Elements of a net -> list (kind, name) with kind switch, pip, mux, out, iob"""
    out, i = [], 0
    while i < len(elements):
        e = elements[i]
        m = re.fullmatch(r"([A-I][A-I]\.8\.[12])\.([0-7])", e)
        if m:
            m2 = re.fullmatch(r"([A-I][A-I]\.8\.[12])\.([0-7])", elements[i + 1])
            assert m2 and m2[1] == m[1], "switch pins not in pairs: %s %s" % (e, elements[i + 1])
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
    """Elements from XACT that are missing from the decoding (config.decode): {kind: [name, ...]}, plus counters
    and the crossings at K muxes as mux lines. IOB elements "LINE:PADn.O/T" are mux sources, "LINE:PADn.I"
    input pips (position from iob.js); clocks of the latched IOBs (.K and the crossings without a PIP bit at
    the K muxes) count under "iob-k" and are not checked (TEST1 names two sources at the top K mux)."""
    kmux_at = {}  # "col:row" of the crossing with the stub -> "Pnn.K source"
    for pin, km in db.kmuxes.items():
        for ent in km.sources:
            if ent.kind == "route":
                kmux_at["%s:%s" % (ent.col, ent.row)] = "%s.K %s" % (pin, ent.line)
    kmux = []
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
    # buffer off or always on: the T bits carry the mode, the mux then does not select a routed line at the
    # T input (in TEST1 e.g. P8 "BUF:" with a net at P8.T)
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
            if kind == "out":  # X -> row io6, Y -> row y of the CLB
                clb, line = name.split()
                row = "row.%s.%s" % (clb[0], "io6" if clb.endswith(".X") else "y")
                kind, name = "pip", "%s:%s" % (line, row)
            if kind == "pip" and name not in pip_names:
                kind = "iob-k"  # crossing without a PIP bit: source of a K mux (clock of latched IOBs)
                if name in kmux_at:
                    kmux.append(kmux_at[name])
            count[kind] += 1
            if kind != "iob-k" and (kind, name) not in have:
                missing[kind].append(name)
    return missing, count, kmux


def check_nets(nets, graph, raw, skip=()):
    """Does the graph, with the programmed bits, connect the CLB and IOB pins of each net, and only these?
    skip: pins that do not count (T inputs with buffer off/on). Result: list (net, pins, state) with state
    ok, separated (pins in several parts) or connected to (pins of another net in the same part)."""
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
            r[2] = "separated"
        elif parts:
            other = owner[next(iter(parts))]
            r[2] = "ok" if other == r[0] else "connected to %s" % other
        else:
            r[2] = "no CLB pins"
    return result


def parse_blocks(path=None):
    """{block: {"base": ..., "config": {field: value}, "equate": [(F/G, equation)]}} (CLBs and IOBs)"""
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
    """Deviations of the decoded blocks (items clb/iob/mux from config.decode) from Config and Equate:
    list (block, text). Empty fields in XACT (unused) do not count; for F/G, XACT names only the
    used inputs, which must be among the selected ones."""
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
                    bad.append((name, "%s:%s, decoded %s" % (k, v, got.get(k))))
            continue
        f = clb[name]
        if b["base"] != f["BASE"]:
            bad.append((name, "Base %s, decoded %s" % (b["base"], f["BASE"])))
        for k in ("X", "Y", "Q", "SET", "RES", "CLK"):
            v = b["config"].get(k, "")
            if (v or k in ("SET", "RES", "CLK")) and v != f[k]:
                bad.append((name, "%s:%s, decoded %s" % (k, v, f[k])))
        for lut, eq in b["equate"]:
            ins = f[lut].split(":")
            table = int(f["LUT" + lut], 16)
            if f["BASE"] == "F":  # 4 variables, B = 1: table F
                table, ins = int(f["LUTF"], 16) << 8 | int(f["LUTG"], 16), ins + ["B"]
            for i in range(1 << len(ins)):
                vals = [(v, (i >> k) & 1) for k, v in enumerate(ins)]
                if any(a == c and x != y for a, x in vals for c, y in vals):
                    continue  # the same input twice: combination cannot occur
                env = dict({v: 0 for v in "ABCDQ"}, **dict(vals))
                if _eval(eq, env) != (table >> i) & 1:
                    bad.append((name, "%s = %s does not match LUT%s %s (%s)" % (lut, eq, lut, f["LUT" + lut], f[lut])))
                    break
    return bad


# --- Configuration -> LCA (cross-check with MAKEBITS) -------------------------------------------------
PIN = re.compile(r"[A-H][A-H]\.[ABCDKXY]|P\d+\.[IOTK]|CLK\.(AA|II)\.[IO]")
DRIVER = re.compile(r"[A-H][A-H]\.[XY]|PAD\d+\.I|CLK\.(AA|II)\.O")


def _equation(ins, table):
    """Equation in XACT style (~, *, +) as a sum of the minterms over the inputs ins (bit i of the table:
    input k = (i >> k) & 1); None for the constant 0"""
    names = list(dict.fromkeys(ins))
    terms = []
    for v in range(1 << len(names)):
        val = {n: (v >> k) & 1 for k, n in enumerate(names)}
        if (table >> sum(val[x] << k for k, x in enumerate(ins))) & 1:
            terms.append("*".join(n if val[n] else "~" + n for n in names))
    return "+".join("(%s)" % t for t in terms) if terms else None


def _clb_block(name, f):
    """Editblk of a CLB from the fields of the text format (blocks.parse_fields)"""
    base, clk = f["BASE"], f["CLK"]
    uses = {f["X"], f["Y"], f["SET"], f["RES"], clk.split(":")[0]} | ({"F"} if clk else set())
    out = ["Editblk %s" % name, "Base %s" % base]
    luts = []
    if base == "F":  # one function of 4 variables, B = 1 selects table F
        luts.append(("F", f["F"].split(":") + ["B"], int(f["LUTF"], 16) << 8 | int(f["LUTG"], 16)))
    else:
        for lut in ("F", "G"):
            if lut in uses or int(f["LUT" + lut], 16):
                luts.append((lut, f[lut].split(":"), int(f["LUT" + lut], 16)))
    cfg = {lut: ":".join(dict.fromkeys(ins)) for lut, ins, _ in luts}
    fg = "F:%s" % cfg.get("F", "") if base == "F" else "F:%s G:%s" % (cfg.get("F", ""), cfg.get("G", ""))
    out.append("Config X:%s Y:%s %s Q:%s SET:%s RES:%s CLK:%s " % (
        f["X"], f["Y"], fg, f["Q"] if clk else "", f["SET"], f["RES"], clk))
    for lut, ins, table in luts:
        eq = _equation(ins, table)
        if eq:
            out.append("Equate %s = %s" % (lut, eq))
    return out + ["Endblk"]


def _coords(db, g, cn):
    """G positions ({xGy} in XACT) that program a connection; switch matrix: both pins one after the other"""
    from . import switches
    if cn.kind in ("pip", "out", "clkout", "junction", "iobi"):
        return [db.entries[cn.bits[0]].key[0]]
    if cn.kind == "switch":
        sm, pins = cn.name.split()
        return ["%dG%d" % switches.pin_g(g.sm_g[sm], int(p)) for p in pins.split("-")]
    if cn.kind == "mux":
        m = db.muxes[cn.b]
        ent = m.sources[m.codes[cn.code]]
    elif cn.kind in ("iobo", "iobt"):
        iob = db.iobs[cn.b.split(".")[0]]
        lst, codes = (iob.o, iob.omux) if cn.kind == "iobo" else (iob.t, iob.tmux)
        ent = lst[codes[cn.code]]
    elif cn.kind == "iobk":
        km = db.kmuxes[cn.name.split(".")[0]]
        ent = km.sources[km.codes[cn.code]]
    elif cn.kind == "clkbuf":
        cm = db.clkmuxes[cn.name.split()[0]]
        ent = cm.sources[cm.codes[cn.code]]
    else:
        return []
    if not ent.g:
        raise ValueError("%s: no G position known" % cn.name)
    return [ent.g]


def write(db, g, lines, part="2064PC68", speed="-70", title="DESIGN"):
    """Configuration (lines from config.parse_text, e.g. from nextpnr) as LCA for MAKEBITS: per net the pins
    (Addnet) and the G positions of the programmed elements (Program, MAKEBITS reads only these), per used CLB
    or IOB a block with Base, Config and Equate. The nets follow from the connectivity of the connections in
    the lines, split at the clock buffers (CLK.AA.I/CLK.II.I on the net of the source, CLK.AA.O/CLK.II.O on
    the clock net). MAKEBITS determines the direction of the repowering buffers and the options itself.
    Result: text with CRLF. ValueError for a line without a connection in the graph or without a G position."""
    from . import blocks
    by_cfg = collections.defaultdict(list)
    for cn in g.conns:
        t = g.cfg(cn)
        if t:
            by_cfg[t].append(cn)
    conns = []
    for l in lines:
        if l.kind == "switch":
            a, b = sorted(int(p) for p in l.value.split("-"))
            key = "switch %s %d-%d" % (l.name, a, b)
        elif l.kind in ("pip", "mux") and l.value not in ("on", "off"):
            key = ("%s %s %s" % (l.kind, l.name, l.value)).strip()
        else:
            continue
        if key not in by_cfg:
            raise ValueError("line %d (%s): no connection in the graph" % (l.lineno, key))
        conns += by_cfg[key][:1]
    latched = {l.name for l in lines if l.kind == "iob" and blocks.parse_fields(l.value).get("I") == "Q"}
    conns += [cn for cn in g.conns if cn.kind == "iobkin" and cn.b[:-2] in latched]

    parent = {}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    buf_out = {"GCLK": "CLK.AA.O", "ACLK": "CLK.II.O"}
    for cn in conns:
        if cn.kind == "clkbuf":  # split at the buffer: pin CLK.AA.I or CLK.II.I on the net of the source
            parent[find(cn.name.split()[0])] = find(cn.a)
        else:
            parent[find(cn.a)] = find(cn.b)
    for node, pin in buf_out.items():
        if node in parent:
            parent[find(pin)] = find(node)
    members, progs = collections.defaultdict(list), collections.defaultdict(list)
    for n in list(parent):
        members[find(n)].append(n)
    for cn in conns:
        progs[find(cn.a)].append(_coords(db, g, cn))

    # pads with XACT's names PADn (independent of the package; in XACT, Pnn would be the package pin)
    from .iobmux import pads
    pad = {p: n for p, _, _, n in pads()}
    xname = lambda n: re.sub(r"^(P\d+)(?=\.|$)", lambda m: pad[m[1]], n)  # noqa: E731
    out = [";: %s.LCA (%s%s), xc2064lca (arch/xc2064)" % (title, part, speed), "Version 2",
           "Design %s 8 0" % part, "Speed %s" % speed]
    nets = []
    for r, nodes in members.items():
        pins = sorted((xname(n) for n in nodes if PIN.fullmatch(n)), key=lambda n: (not DRIVER.fullmatch(n), n))
        if len(pins) > 1 or progs[r]:
            nets.append((pins, progs[r]))
    for k, (pins, prog) in enumerate(sorted(nets)):
        out.append("Addnet N%d %s " % (k, " ".join(pins)))
        line = []  # MAKEBITS pairs the two pins of a switch matrix only within one line
        for i, coords in enumerate(prog):
            line += coords
            if len(line) >= 32 or i == len(prog) - 1:
                out.append("Program N%d %s " % (k, " ".join("{%s}" % p for p in line)))
                line = []
    tmode = {l.name[:-2]: l.value for l in lines if l.kind == "mux" and l.name.endswith(".T")}
    for l in lines:
        if l.kind == "clb":
            f = dict(blocks.DEFAULT_CLB)
            f.update(blocks.parse_fields(l.value))
            out += _clb_block(l.name, f)
        elif l.kind == "iob":
            buf = {"on": "ON", "off": ""}.get(tmode.get(l.name, "off"), "TRI")
            out += ["Editblk %s" % xname(l.name), "Base IO",
                    "Config I:%s BUF:%s " % (blocks.parse_fields(l.value).get("I", "PAD"), buf), "Endblk"]
    return "\r\n".join(out) + "\r\n"
