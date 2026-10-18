# Trial run of the XACT tools in run.sh, without DOSBox: checks what xc2064lca and xc2064xnf write.
#   check_xact.py lca <design.LCA> <design.cfg.txt> <design.rbt>
#     Blocks: for every CLB and every IOB of the text file exactly one Editblk, Base, Config and Equate as in the
#     bitstream (lca.check_blocks). Nets: the pins of every Addnet are connected in the routing graph through the
#     programmed bits of the bitstream, different nets are separate (lca.check_nets; separated at the
#     clock buffers as in the LCA). What MAKEBITS makes of it is checked only by the comparison in DOSBox.
#   check_xact.py xnf <design.xnf> <yosys.log> [--lut] [--iobff] [--pcf design.pcf]
#     Structure (header, SYM ... END, EXT, EOF), only the symbols from xc2064db/xnf.py with their pins, every net
#     with exactly one driver (a bidirectional pad additionally the outside world), pads only on buffers, at most
#     one GCLK and one ACLK, EQN only over its own pins. As many storage elements and pads as in
#     synth_xc2064 (statistics at the end of yosys.log), with --iobff also as many INFF, without it none; with
#     --pcf a LOC for every pin of the PCF.
# Prints one line with the result and errors on stderr, and in that case exits with 1.
import argparse
import collections
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from xc2064db import bitstream, config, graph, lca, xnf  # noqa: E402
from xc2064db.iobmux import pads  # noqa: E402


def check_lca(path, cfg, rbt):
    errors = []
    db = config.Database()
    g = graph.Graph(db.entries, db.lines)
    raw = bitstream.read(rbt).raw
    items, problems = config.decode(db, raw)
    errors += ["Bitstream: %s" % p for p in problems]
    pin_of = {n: p for p, _, _, n in pads()}  # XACT's PADn -> pad Pnn
    to_pin = lambda n: re.sub(r"^PAD\d+", lambda m: pin_of[m[0]], n)  # noqa: E731

    blocks = {to_pin(k): v for k, v in lca.parse_blocks(path).items()}
    used = {l.name for l in config.parse_text(open(cfg, encoding="utf-8").read()) if l.kind in ("clb", "iob")}
    errors += ["Block %s missing" % b for b in sorted(used - set(blocks))]
    errors += ["Block %s is not used" % b for b in sorted(set(blocks) - used)]
    errors += ["Block %s: %s" % b for b in lca.check_blocks(blocks, items)]

    nets = {n: {"pins": [to_pin(p) for p in v["pins"]], "elements": []} for n, v in lca.parse(path).items()}
    skip = {it.name for it in items if it.kind == "mux" and it.name.endswith(".T") and it.value in ("off", "on")}
    cut = types.SimpleNamespace(conns=[cn for cn in g.conns if cn.kind != "clkbuf"])
    for name, pins, state in lca.check_nets(nets, cut, raw, skip):
        if state not in ("ok", "no CLB pins"):
            errors.append("Net %s (%s): %s" % (name, " ".join(pins), state))
    return errors, "LCA: %d nets, %d blocks" % (len(nets), len(blocks))


# XNF symbol -> (inputs that must be present, inputs that may be present, output)
ONE = ({"I"}, set(), "O")
SYMBOLS = {
    "INV": ONE, "BUF": ONE, "IBUF": ONE, "OBUF": ONE, "GCLK": ONE, "ACLK": ONE,
    "OBUFT": ({"I", "T"}, set(), "O"),
    "EQN": (set(), {"I0", "I1", "I2", "I3"}, "O"),
    "DFF": ({"D", "C"}, {"RD", "SD"}, "Q"),
    "DLAT": ({"D", "G"}, {"RD", "SD"}, "Q"),
    "INFF": ({"D", "C"}, set(), "Q"),
}
for _gate in set(sym for sym, _ in xnf.GATES.values()):
    SYMBOLS[_gate] = ({"1", "2"}, set(), "O")
STORAGE = {"DFF", "DLAT", "INFF"}
IO_CELLS = ("XC2000_INBUF", "XC2000_INFF", "XC2000_OUTBUF", "XC2000_TOBUF", "XC2000_IOBUF")


def synth_stats(log):
    """Cell counts of the last statistics in yosys.log (like the // expected: lines in run.sh)"""
    stats = {}
    for line in open(log, encoding="utf-8", errors="replace"):
        w = line.split()
        if len(w) == 2 and w[0].isdigit() and w[1].startswith("XC2000_"):
            stats[w[1]] = int(w[0])
    return stats


def check_xnf(path, log, iobff, pcf):
    errors = []
    recs = [[f.strip() for f in line.split(",")] for line in open(path, encoding="ascii").read().splitlines()
            if line.strip()]
    if not recs or recs[0][:1] != ["LCANET"] or recs[-1] != ["EOF"] or not any(r[0] == "PART" for r in recs):
        errors.append("Header (LCANET, PART) or EOF missing")
    syms, exts, pwr, cur = [], {}, set(), None
    for r in recs:
        kind = r[0]
        if kind == "SYM":
            if cur:
                errors.append("SYM %s without END" % cur["name"])
            cur = {"name": r[1], "type": r[2], "params": r[3:], "pins": []}
        elif kind == "PIN":
            if not cur:
                errors.append("PIN outside a SYM: %s" % ", ".join(r))
                continue
            cur["pins"].append((r[1], r[2], r[3], "INV" in r[4:]))
        elif kind == "END":
            if cur:
                syms.append(cur)
            cur = None
        elif kind == "EXT":
            if r[1] in exts:
                errors.append("Pad %s twice" % r[1])
            loc = [f[4:] for f in r[3:] if f.startswith("LOC=")]
            exts[r[1]] = (r[2], loc[0] if loc else None)
        elif kind == "PWR":
            pwr.add(r[2])
        elif kind not in ("LCANET", "PROG", "PART", "EOF"):
            errors.append("unknown record %s" % kind)

    drivers, readers = collections.defaultdict(list), collections.defaultdict(list)
    count = collections.Counter()
    for s in syms:
        t = s["type"]
        count[t] += 1
        if t not in SYMBOLS:
            errors.append("%s: symbol %s does not exist in xnf.py" % (s["name"], t))
            continue
        need, may, out = SYMBOLS[t]
        ins = {p for p, d, _, _ in s["pins"] if d == "I"}
        outs = [p for p, d, _, _ in s["pins"] if d == "O"]
        if outs != [out] or not need <= ins or not ins <= need | may or len(ins) + 1 != len(s["pins"]):
            errors.append("%s (%s): pins %s" % (s["name"], t, " ".join("%s:%s" % (p, d) for p, d, _, _ in s["pins"])))
        if t == "EQN":
            eq = [p[4:] for p in s["params"] if p.startswith("EQN=")]
            if not ins or len(eq) != 1 or not re.fullmatch(r"[()~*+I0-3]+", eq[0]) \
                    or set(re.findall(r"I[0-3]", eq[0])) != ins:
                errors.append("%s: EQN %s does not match the pins %s" % (s["name"], eq, " ".join(sorted(ins))))
        for p, d, net, _ in s["pins"]:
            (drivers if d == "O" else readers)[net].append((s, p))

    for net, ds in drivers.items():
        if len(ds) > 1 or net in pwr or (net in exts and exts[net][0] == "I"):
            errors.append("Net %s has several drivers" % net)
    for net in readers:
        if net not in drivers and net not in pwr and not (net in exts and exts[net][0] in "IB"):
            errors.append("Net %s has no driver" % net)
    pad_use = {("IBUF", "I"), ("INFF", "D"), ("OBUF", "O"), ("OBUFT", "O")}
    for net in exts:
        for s, p in drivers.get(net, []) + readers.get(net, []):
            if (s["type"], p) not in pad_use:
                errors.append("Pad %s is connected to %s.%s (%s)" % (net, s["name"], p, s["type"]))
    for net, (kind, _) in exts.items():
        d = [s["type"] for s, _ in drivers.get(net, [])]
        r = [s["type"] for s, _ in readers.get(net, [])]
        ok = {"I": not d and len(r) == 1, "O": d == ["OBUF"] and not r, "T": d == ["OBUFT"] and not r,
              "B": d == ["OBUFT"] and r == ["IBUF"]}.get(kind)
        if not ok:
            errors.append("Pad %s (%s): drivers %s, readers %s" % (net, kind, d or "-", r or "-"))
    for buf in ("GCLK", "ACLK"):
        if count[buf] > 1:
            errors.append("%d symbols %s" % (count[buf], buf))
    for s in syms:
        if s["type"] in ("GCLK", "ACLK"):
            src = [d["type"] for d, _ in drivers.get(s["pins"][0][2], [])]
            if src != ["IBUF"]:
                errors.append("%s %s does not read an IBUF (%s)" % (s["type"], s["name"], src))

    st = synth_stats(log)
    storage = sum(count[t] for t in STORAGE)
    if storage != st.get("XC2000_DFF", 0) + st.get("XC2000_INFF", 0):
        errors.append("%d storage elements, synth_xc2064 %d XC2000_DFF and %d XC2000_INFF"
                      % (storage, st.get("XC2000_DFF", 0), st.get("XC2000_INFF", 0)))
    if count["INFF"] != (st.get("XC2000_INFF", 0) if iobff else 0):
        errors.append("%d INFF, synth_xc2064 %d XC2000_INFF" % (count["INFF"], st.get("XC2000_INFF", 0)))
    io = sum(st.get(c, 0) for c in IO_CELLS)
    if len(exts) != io:
        errors.append("%d pads, synth_xc2064 %d IO cells" % (len(exts), io))
    if pcf:
        want = sorted(xnf.read_pcf(open(pcf, encoding="utf-8").read()).values())
        got = sorted(loc for _, loc in exts.values() if loc)
        if got != want:
            errors.append("LOC %s, PCF %s" % (" ".join(got), " ".join(want)))
    return errors, "XNF: %d symbols, %d storage elements, %d pads" % (len(syms), storage, len(exts))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="what", required=True)
    a = sub.add_parser("lca")
    a.add_argument("lca")
    a.add_argument("cfg")
    a.add_argument("rbt")
    x = sub.add_parser("xnf")
    x.add_argument("xnf")
    x.add_argument("log")
    x.add_argument("--lut", action="store_true", help="logic as EQN (does not change the checks)")
    x.add_argument("--iobff", action="store_true")
    x.add_argument("--pcf")
    args = ap.parse_args()
    if args.what == "lca":
        errors, summary = check_lca(args.lca, args.cfg, args.rbt)
    else:
        errors, summary = check_xnf(args.xnf, args.log, args.iobff, args.pcf)
    for e in errors:
        print("check_xact: %s" % e, file=sys.stderr)
    print("%s, %s" % (summary, "%d errors" % len(errors) if errors else "ok"))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
