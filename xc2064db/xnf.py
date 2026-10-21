# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
"""XNF netlist (Xilinx Netlist Format) for XACT's XC2000 flow from a flat yosys JSON netlist
(tools/xc2064xnf). XACT turns it into an unplaced LCA file with XNFMERGE, XNFPREP, XNFMAP and MAP2LCA;
the mapping onto CLBs and IOBs is therefore that of XNFMAP, not that of synth_xc2064.

Only symbols from XACT\\DATA\\XLXLGL2K.XNF (allowed symbols of the XC2000 family) are used:

| yosys | XNF |
|---|---|
| `$_AND_` `$_NAND_` `$_OR_` `$_NOR_` `$_XOR_` `$_XNOR_` | gate of the same name, inputs 1, 2, output O |
| `$_ANDNOT_` `$_ORNOT_` | AND or OR, input 2 with INV |
| `$_NOT_` `$_BUF_` | INV or BUF (I, O) |
| `$lut` (up to 4 inputs), `$_MUX_`, `$_NMUX_`, `$_AOI3_` ... `$_OAI4_` | EQN (I0-I3, minimized sum of products) |
| `$_DFF_P_`/`N_`, `$_DFFSR_PPP_`/`NPP_` | DFF (D, C, RD, SD, Q); negative edge: C with INV |
| `$_DLATCH_P_`/`N_`, `$_DLATCHSR_PPP_`/`NPP_` | DLAT (D, G, RD, SD, Q); G with INV for `_N_` |
| input, output, `$_TBUF_` at the output | EXT with IBUF (I), OBUF (O), OBUFT (T, T = not E) or OBUFT and IBUF (B) |
| clock from a pad that clocks only storage elements | IBUF and GCLK (the second one: ACLK) |
| with iobff: FF as the only reader of an input, rising edge, no set/reset | INFF (D at the pad, C, Q) |

Nets: pads are named like the ports (`LEDS<0>`, buses with angle brackets as with Xilinx), the output of their
IBUF `<Pad>_I`, that of a clock buffer `<Pad>_GCLK` or `<Pad>_ACLK`. Internal nets are named after the shortest
public name in yosys (hierarchy with `/`), otherwise `$N<Bit>`. Constants are the nets GND and VCC (PWR).
"""
import re

# yosys gate -> (XNF symbol, inverted inputs)
GATES = {
    "$_AND_": ("AND", ""), "$_NAND_": ("NAND", ""), "$_OR_": ("OR", ""), "$_NOR_": ("NOR", ""),
    "$_XOR_": ("XOR", ""), "$_XNOR_": ("XNOR", ""), "$_ANDNOT_": ("AND", "B"), "$_ORNOT_": ("OR", "B"),
}
# cells without a matching gate: inputs and function, written as EQN
FUNCS = {
    "$_MUX_": ("ABS", lambda a, b, s: b if s else a),
    "$_NMUX_": ("ABS", lambda a, b, s: not (b if s else a)),
    "$_AOI3_": ("ABC", lambda a, b, c: not ((a and b) or c)),
    "$_OAI3_": ("ABC", lambda a, b, c: not ((a or b) and c)),
    "$_AOI4_": ("ABCD", lambda a, b, c, d: not ((a and b) or (c and d))),
    "$_OAI4_": ("ABCD", lambda a, b, c, d: not ((a or b) and (c or d))),
}
# storage elements after dfflegalize as in synth_xc2064: yosys cell -> (symbol, clock or gate port, inverted)
STORAGE = {
    "$_DFF_P_": ("DFF", "C", False), "$_DFF_N_": ("DFF", "C", True),
    "$_DFFSR_PPP_": ("DFF", "C", False), "$_DFFSR_NPP_": ("DFF", "C", True),
    "$_DLATCH_P_": ("DLAT", "E", False), "$_DLATCH_N_": ("DLAT", "E", True),
    "$_DLATCHSR_PPP_": ("DLAT", "E", False), "$_DLATCHSR_NPP_": ("DLAT", "E", True),
}
CLOCK_PIN = {"DFF": "C", "DLAT": "G"}
IGNORED = {"$scopeinfo"}


def yosys_script(top, lut, json_file):
    """yosys commands (separated by ;) for a netlist that write can translate: flat, storage elements as in
    synth_xc2064 (FF or latch, clock of either polarity, asynchronous set/reset, 0 after loading), logic as
    simple gates, with lut as LUTs with up to 4 inputs (ABC)"""
    return "; ".join([
        "hierarchy -check " + ("-top " + top if top else "-auto-top"),
        "proc", "flatten", "tribuf -logic", "deminout",
        "synth -nofsm -run coarse:fine",
        "opt -fast -full", "memory_map", "opt -full", "techmap", "opt -fast",
        "dfflegalize -cell $_DFF_P_ 0 -cell $_DFF_N_ 0 -cell $_DFFSR_PPP_ 0 -cell $_DFFSR_NPP_ 0"
        " -cell $_DLATCH_P_ 0 -cell $_DLATCH_N_ 0 -cell $_DLATCHSR_PPP_ 0 -cell $_DLATCHSR_NPP_ 0",
        "opt_clean",
        "abc -lut 4" if lut else "abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT",
        "opt_clean", "setundef -undriven -zero", "check", "write_json " + json_file])


def read_pcf(text):
    """set_io <port> <pin> -> {port: pin}, port as in Verilog (leds[0]); options starting with - are skipped"""
    pins = {}
    for n, line in enumerate(text.splitlines(), 1):
        words = line.split("#")[0].split()
        if not words:
            continue
        args = [w for w in words[1:] if not w.startswith("-")]
        if words[0] != "set_io" or len(args) != 2:
            raise ValueError("PCF line %d: expected set_io <port> <pin>" % n)
        pins[args[0]] = args[1]
    return pins


def top_module(netlist, top=None):
    """(name, module) of the top module of a yosys JSON netlist"""
    modules = netlist["modules"]
    if top:
        if top not in modules:
            raise ValueError("module %s is missing from the netlist" % top)
        return top, modules[top]
    tops = [m for m, mod in modules.items() if _int(mod.get("attributes", {}).get("top", 0))]
    if len(tops) != 1:
        tops = list(modules) if len(modules) == 1 else tops
    if len(tops) != 1:
        raise ValueError("top module ambiguous (%s), specify --top" % ", ".join(sorted(modules)))
    return tops[0], modules[tops[0]]


def _int(v):
    return int(v, 2) if isinstance(v, str) else int(v)


def _clean(name):
    """yosys name -> XNF name: upper case, hierarchy with /, bit index with <>, otherwise only A-Z 0-9 _ $"""
    name = name.lstrip("\\").upper().replace(".", "/").replace("[", "<").replace("]", ">")
    return re.sub(r"[^A-Z0-9_$/<>]", "_", name)


def _bit_names(name, entry):
    """Name of each bit of a port or net (buses with index, direction and offset as in the Verilog)"""
    bits = entry["bits"]
    if len(bits) == 1:
        return [name]
    offset, upto = entry.get("offset", 0), entry.get("upto", 0)
    return ["%s[%d]" % (name, offset + (len(bits) - 1 - i if upto else i)) for i in range(len(bits))]


def _sop(n, ones):
    """Minterms ones over n inputs -> prime implicants (value, mask of the free inputs), covered greedily"""
    terms, primes = {(m, 0) for m in ones}, set()
    while terms:
        merged, nxt = set(), set()
        for a in terms:
            for b in terms:
                d = a[0] ^ b[0]
                if a[1] == b[1] and d and not d & (d - 1):
                    nxt.add((a[0] & b[0], a[1] | d))
                    merged |= {a, b}
        primes |= terms - merged
        terms = nxt
    cover, left = [], set(ones)
    while left:
        best = max(sorted(primes), key=lambda p: (sum(1 for m in left if m & ~p[1] == p[0]), p[1]))
        cover.append(best)
        left = {m for m in left if m & ~best[1] != best[0]}
    return cover


class _Writer:
    def __init__(self, module, pins, clkbuf, gclk, aclk, iobff):
        self.module = module
        self.cells = {n: c for n, c in module.get("cells", {}).items() if c["type"] not in IGNORED}
        self.nets, self.syms = {"GND", "VCC"}, set()
        self.consts = set()           # used constants (0, 1)
        self.alias = {}               # bit -> "0"/"1" for cells with a constant output
        self.sink_net = {}            # bit of an input -> net that the logic reads (IBUF or clock buffer)
        self.internal = {}
        self.body, self.ext = [], []
        self.stats = {"gates": 0, "EQN": 0, "FFs": 0, "Latches": 0, "IOB-FFs": 0, "Pads": 0}
        self.clkbufs = []
        self._check_cells()
        self._names()
        self._ports(pins or {})
        self._clocks(clkbuf, gclk, aclk)
        self.inff = self._iobffs() if iobff else {}

    # Checks and connectivity

    def _check_cells(self):
        bad = sorted({c["type"] for c in self.cells.values()
                      if c["type"] not in GATES and c["type"] not in FUNCS and c["type"] not in STORAGE
                      and c["type"] not in ("$_NOT_", "$_BUF_", "$lut", "$_TBUF_")})
        if bad:
            raise ValueError("cells without an XNF counterpart: %s (synthesize the netlist flat and with the "
                             "script of xc2064xnf)" % ", ".join(bad))
        self.drivers, self.sinks = {}, {}
        for name, c in self.cells.items():
            for port, bits in c["connections"].items():
                for b in bits:
                    if c["port_directions"][port] == "output":
                        if isinstance(b, int):
                            self.drivers[b] = (name, port)
                    else:
                        self.sinks.setdefault(b, []).append((name, port))
            if c["type"] == "$lut":
                if _int(c["parameters"]["WIDTH"]) > 4:
                    raise ValueError("LUT %s has more than 4 inputs" % name)
                table = self._lut_table(c)
                if len(set(table)) == 1:
                    self.alias[c["connections"]["Y"][0]] = "1" if table[0] else "0"

    @staticmethod
    def _lut_table(c):
        lut, width = c["parameters"]["LUT"], _int(c["parameters"]["WIDTH"])
        value = _int(lut)
        return [value >> k & 1 for k in range(1 << width)]

    def _names(self):
        """Candidates for internal net names: public names except ports, shortest first"""
        ports = self.module["ports"]
        self.cands, self.port_cands = {}, {}
        for name, entry in self.module.get("netnames", {}).items():
            if entry.get("hide_name"):
                continue
            target = self.port_cands if name in ports else self.cands
            for b, label in zip(entry["bits"], _bit_names(name, entry)):
                if isinstance(b, int):
                    target.setdefault(b, []).append(_clean(label))

    def _unique(self, name, used):
        base, n = name, 1
        while name in used:
            n += 1
            name = "%s_%d" % (base, n)
        used.add(name)
        return name

    def net(self, b):
        """Net name that the logic reads for bit b"""
        b = self.alias.get(b, b)
        if isinstance(b, str):
            v = "1" if b == "1" else "0"     # x and z become 0
            self.consts.add(v)
            return "VCC" if v == "1" else "GND"
        if b in self.sink_net:
            return self.sink_net[b]
        if b not in self.internal:
            if b in self.cands:
                name = min(self.cands[b], key=lambda s: (s.count("/"), len(s), s))
            elif b in self.port_cands:
                name = min(self.port_cands[b], key=lambda s: (len(s), s)) + "_O"
            else:
                name = "$N%d" % b
            self.internal[b] = self._unique(name, self.nets)
        return self.internal[b]

    def _is_zero(self, b):
        b = self.alias.get(b, b)
        return isinstance(b, str) and b != "1"

    # Pads

    def _ports(self, pins):
        self.inputs, self.outputs = [], []     # (pad, bit, port name as in Verilog)
        tbufs = {c["connections"]["Y"][0]: n for n, c in self.cells.items() if c["type"] == "$_TBUF_"}
        port_bits = set()
        for name, p in self.module["ports"].items():
            for b, label in zip(p["bits"], _bit_names(name, p)):
                pad = self._unique(_clean(label), self.nets)
                loc = pins.pop(label, None)
                port_bits.add(b)
                if p["direction"] == "input" or (p["direction"] == "inout" and b not in tbufs):
                    self.inputs.append((pad, b, label, loc))
                else:
                    self.outputs.append((pad, b, label, loc))
        if pins:
            raise ValueError("PCF names ports that do not exist: %s" % ", ".join(sorted(pins)))
        self.tbufs = tbufs
        for b, cell in tbufs.items():
            if b not in port_bits:
                raise ValueError("tristate buffer %s drives no port (tribuf -logic missing?)" % cell)

    def _clocks(self, clkbuf, gclk, aclk):
        """Clock buffers: GCLK and ACLK, each for one input (default: the two inputs that drive only clocks of
        storage elements, with the most sinks)"""
        self.buffered = {}
        by_label = {label: b for _, b, label, _ in self.inputs}
        for buf, label in (("GCLK", gclk), ("ACLK", aclk)):
            if label:
                if label not in by_label:
                    raise ValueError("--%s: no input %s" % (buf.lower(), label))
                self.buffered[by_label[label]] = buf
        if not clkbuf:
            return
        out_bits = {b for _, b, _, _ in self.outputs}
        cands = []
        for _, b, label, _ in self.inputs:
            sinks = self.sinks.get(b, [])
            if sinks and b not in out_bits and b not in self.buffered and all(
                    self.cells[n]["type"] in STORAGE and STORAGE[self.cells[n]["type"]][1] == port
                    for n, port in sinks):
                cands.append((-len(sinks), label, b))
        free = [buf for buf in ("GCLK", "ACLK") if buf not in self.buffered.values()]
        for (_, _, b), buf in zip(sorted(cands), free):
            self.buffered[b] = buf

    def _iobffs(self):
        """{bit of an input: FF} for FFs that go into the IOB as with xc2064_iobff (INFF): only reader of the
        input, rising edge, no set/reset"""
        inff = {}
        out_bits = {b for _, b, _, _ in self.outputs}
        for _, b, _, _ in self.inputs:
            sinks = self.sinks.get(b, [])
            if len(sinks) != 1 or b in out_bits or b in self.buffered:
                continue
            name, port = sinks[0]
            conn = self.cells[name]["connections"]
            if port == "D" and self.cells[name]["type"] in ("$_DFF_P_", "$_DFFSR_PPP_") and all(
                    self._is_zero(conn[p][0]) for p in ("S", "R") if p in conn):
                inff[b] = name
        return inff

    # Output

    def sym(self, name, kind, pins, params=""):
        self.body.append("SYM, %s, %s%s" % (self._unique(name, self.syms), kind, ", " + params if params else ""))
        for pin, direction, net, inv in pins:
            self.body.append("PIN, %s, %s, %s%s" % (pin, direction, net, ", , INV" if inv else ""))
        self.body.append("END")

    def _eqn(self, out, inputs, table):
        """EQN from the truth table (entry k: output for inputs = bits of k)"""
        cover = _sop(len(inputs), [k for k, v in enumerate(table) if v])
        used = sorted({i for value, mask in cover for i in range(len(inputs)) if not mask >> i & 1})
        terms = ["*".join(("I%d" if value >> i & 1 else "~I%d") % i for i in range(len(inputs))
                          if not mask >> i & 1) for value, mask in cover]
        pins = [("I%d" % i, "I", self.net(inputs[i]), False) for i in used] + [("O", "O", self.net(out), False)]
        self.sym(self.net(out), "EQN", pins, "EQN=(%s)" % "+".join("(%s)" % t for t in terms))
        self.stats["EQN"] += 1

    def _cell(self, c):
        kind, conn = c["type"], c["connections"]
        if kind in GATES:
            sym, inverted = GATES[kind]
            out = conn["Y"][0]
            self.sym(self.net(out), sym, [("1", "I", self.net(conn["A"][0]), "A" in inverted),
                                          ("2", "I", self.net(conn["B"][0]), "B" in inverted),
                                          ("O", "O", self.net(out), False)])
            self.stats["gates"] += 1
        elif kind in ("$_NOT_", "$_BUF_"):
            out = conn["Y"][0]
            self.sym(self.net(out), "INV" if kind == "$_NOT_" else "BUF",
                     [("I", "I", self.net(conn["A"][0]), False), ("O", "O", self.net(out), False)])
            self.stats["gates"] += 1
        elif kind in FUNCS:
            ports, f = FUNCS[kind]
            out = conn["Y"][0]
            table = [bool(f(*(k >> i & 1 for i in range(len(ports))))) for k in range(1 << len(ports))]
            self._eqn(out, [conn[p][0] for p in ports], table)
        elif kind == "$lut":
            out = conn["Y"][0]
            if out not in self.alias:
                self._eqn(out, conn["A"], self._lut_table(c))
        elif kind in STORAGE:
            sym, clock, neg = STORAGE[kind]
            q = conn["Q"][0]
            pins = [("D", "I", self.net(conn["D"][0]), False), (CLOCK_PIN[sym], "I", self.net(conn[clock][0]), neg)]
            for port, pin in (("R", "RD"), ("S", "SD")):
                if port in conn and not self._is_zero(conn[port][0]):
                    pins.append((pin, "I", self.net(conn[port][0]), False))
            self.sym(self.net(q), sym, pins + [("Q", "O", self.net(q), False)])
            self.stats["FFs" if sym == "DFF" else "Latches"] += 1

    def text(self, part, title):
        # First the nets behind the pads, so that the logic reads the IBUF or clock buffer
        ibufs = []    # (pad, IBUF output, clock buffer, its output)
        for pad, b, label, loc in self.inputs:
            if b in self.inff:
                continue
            o = self.sink_net[b] = self._unique(pad + "_I", self.nets)
            buf = self.buffered.get(b)
            if buf:
                self.sink_net[b] = self._unique("%s_%s" % (pad, buf), self.nets)
                self.clkbufs.append("%s %s" % (buf, label))
            ibufs.append((pad, o, buf, self.sink_net[b]))
        for pad, b, label, loc in self.outputs:
            if b in self.tbufs and self.sinks.get(b):
                self.sink_net[b] = self._unique(pad + "_I", self.nets)
                ibufs.append((pad, self.sink_net[b], None, None))
        for pad, o, buf, g in ibufs:
            self.sym(o, "IBUF", [("I", "I", pad, False), ("O", "O", o, False)])
            if buf:
                self.sym(g, buf, [("I", "I", o, False), ("O", "O", g, False)])
        for pad, b, label, loc in self.inputs:
            if b in self.inff:
                conn = self.cells[self.inff[b]]["connections"]
                q = self.net(conn["Q"][0])
                self.sym(q, "INFF", [("D", "I", pad, False), ("C", "I", self.net(conn["C"][0]), False),
                                     ("Q", "O", q, False)])
                self.stats["IOB-FFs"] += 1
            self._ext(pad, "I", loc)
        moved = set(self.inff.values())
        for name, c in self.cells.items():
            if name not in moved:
                self._cell(c)
        inverted = {}     # E bit -> net not E (T of the OBUFT)
        for pad, b, label, loc in self.outputs:
            if b not in self.tbufs:
                self.sym(pad, "OBUF", [("I", "I", self.net(b), False), ("O", "O", pad, False)])
                self._ext(pad, "O", loc)
                continue
            conn = self.cells[self.tbufs[b]]["connections"]
            e = self.alias.get(conn["E"][0], conn["E"][0])
            if isinstance(e, str):
                t = self.net("0" if e == "1" else "1")
            elif e in inverted:
                t = inverted[e]
            else:
                t = inverted[e] = self._unique(pad + "_T", self.nets)
                self.sym(t, "INV", [("I", "I", self.net(e), False), ("O", "O", t, False)])
                self.stats["gates"] += 1
            self.sym(pad, "OBUFT", [("I", "I", self.net(conn["A"][0]), False), ("T", "I", t, False),
                                    ("O", "O", pad, False)])
            self._ext(pad, "B" if self.sinks.get(b) else "T", loc)
        head = ["LCANET, 5", 'PROG, XC2064XNF, 1, "%s"' % title, "PART, %s" % part]
        head += ["PWR, %s, %s" % (v, "VCC" if v == "1" else "GND") for v in sorted(self.consts)]
        return "\r\n".join(head + self.body + self.ext + ["EOF", ""])

    def _ext(self, pad, kind, loc):
        self.ext.append("EXT, %s, %s%s" % (pad, kind, ", , LOC=%s" % loc if loc else ""))
        self.stats["Pads"] += 1


def write(module, part, title="", pins=None, clkbuf=True, gclk=None, aclk=None, iobff=False):
    """XNF text for a flat yosys module (dict from write_json). part as in XACT (2064PC68-70), pins from
    read_pcf, clkbuf: choose the clock buffers automatically, gclk/aclk: input (name as in the Verilog) fixed onto
    the buffer, iobff: input FFs into the IOB (INFF). Returns (text, {counters}, [clock buffers])."""
    w = _Writer(module, dict(pins or {}), clkbuf, gclk, aclk, iobff)
    return w.text(part, title), w.stats, w.clkbufs
