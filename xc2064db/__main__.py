# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
"""Coverage report and cross-checks of the data sources:  python3 -m xc2064db  (in arch/xc2064)

Exits with an error if a cross-check fails. Coverage: which bits the package decodes (since the codes of the
clock buffer inputs became known, all used ones).
"""
import collections
import csv
import re
import sys

from . import bitmap, bitstream, clbmux, config, graph, iobmux, lca, packages, sources, switches
from .lines import Lines

failed = []


def check(ok, text):
    print("  [%s] %s" % ("ok" if ok else "FAIL", text))
    if not ok:
        failed.append(text)


def openxc_pattern():
    """possible_connections from openxc2064 (8x8 matrix, pins 0-7) as pin pairs 1-8"""
    src = sources.read_text(sources.OPENXC_GENERATOR)
    body = re.search(r"possible_connections\s*=\s*\[(.*?)\n\s*\]", src, re.S).group(1)
    rows = [[int(v) for v in re.findall(r"[01]", r)] for r in re.findall(r"\[([^\]]*)\]", body)]
    pairs = {tuple(sorted((i + 1, j + 1))) for i, r in enumerate(rows) for j, v in enumerate(r) if v}
    symmetric = all(rows[i][j] == rows[j][i] for i in range(8) for j in range(8))
    return pairs, symmetric


def main():
    entries = bitmap.load()
    lines = Lines()
    kinds = collections.Counter(e.kind for e in entries)

    print("Bit map %s" % sources.DEF_TXT)
    print("  %s" % ", ".join("%s %d" % kv for kv in sorted(kinds.items(), key=lambda kv: -kv[1])))
    check(not bitmap.duplicates(entries), "every name in the bit map is unique (text format 'bit ...')")
    print("  Note: bits %s are missing from the file, treated as unused" % bitmap.missing(entries))

    print("Lines (draw.js): %d column names, %d row names" % (len(lines.col_name), len(lines.row_name)))
    pips = [e for e in entries if e.kind == "pip"]
    unresolved = [e.key[0] for e in pips if lines.pip_name(e.key[0]) is None]
    check(not unresolved, "all %d PIPs lie on the crossing of two named lines %s"
          % (len(pips), unresolved[:5]))

    conn = switches.connections(entries, lines)
    pats = switches.patterns(conn)
    print("Switch matrices: %d with Magic bits, %d patterns" % (len(conn), len(pats)))
    for pat, names in sorted(pats.items(), key=lambda kv: -len(kv[1])):
        print("  %3d x %2d connections: %s" % (len(names), len(pat), " ".join("%d-%d" % p for p in pat)))
    interior = max(pats, key=lambda p: len(pats[p]))
    check(len(conn) == 154 and len(pats[interior]) == 98, "154 matrices, 98 of them with the interior pattern")
    check(all(set(p) <= set(interior) for p in pats), "every edge pattern is a subset of the interior pattern")
    ox, symmetric = openxc_pattern()
    check(symmetric and ox == set(interior),
          "openxc2064 possible_connections (pins 0-7) = interior pattern from the Magic bits (pins 1-8)")

    muxes = clbmux.muxes(lines, entries)
    nbits = sum(len(m.bits) for m in muxes.values())
    per_pin = collections.defaultdict(set)
    for m in muxes.values():
        per_pin[m.pin].add(len(m.sources))
    print("CLB input muxes (clb.js): %d muxes, %d bits; sources per input %s" % (
        len(muxes), nbits, ", ".join("%s %s" % (p, "-".join(map(str, sorted(v)))) for p, v in sorted(per_pin.items()))))
    check(nbits == kinds["clbmux"], "all %d CLB mux bits of the bit map belong to a mux" % kinds["clbmux"])
    check(all(len(set(v for v in m.codes.values() if v is not None)) == len(m.sources) for m in muxes.values()),
          "every source has exactly one code (source -> bits unique, for xc2064pack)")

    print("openxc2064 %s" % sources.OPENXC)
    check(sources.text_sha1(sources.OPENXC_DEF_TXT) == sources.text_sha1(sources.DEF_TXT),
          "pin_planning/XC2064-def.txt is a copy of Shirriff's file (not an independent source)")
    rows = list(csv.reader(sources.read_text(sources.OPENXC_CSV).splitlines()))
    same = all(rows[i % bitmap.FRAME_BITS][i // bitmap.FRAME_BITS].strip() == e.text
               for i, e in enumerate(entries) if e.text != "(missing)")
    check(len(rows) == bitmap.FRAME_BITS and same,
          "XC2064-spreadsheet.csv is the same bit map, just as a 71 x 160 table")

    print("Routing graph (xc2064db.graph)")
    g = graph.Graph(entries, lines)
    kc = collections.Counter(c.kind for c in g.conns)
    print("  %s" % ", ".join("%s %d" % kv for kv in sorted(kc.items())))
    check(not g.skipped, "every PIP bit belongs to a connection of the graph %s" % list(g.skipped)[:4])
    print("  not modelled (iob.js): %s" % ", ".join("%s %s" % (p, s) for p, s, _ in g.unmodelled))

    print("Clock buffer inputs (iobmux.clkmuxes, codes from MAKEBITS)")
    cms = iobmux.clkmuxes(lines, entries)
    for name, cm in sorted(cms.items()):
        print("  %s (%s): %s" % (name, cm.net, ", ".join("%d %s" % (c, iobmux.source_name(cm.sources[k]))
                                                          for c, k in sorted(cm.codes.items(), reverse=True))))
    check(sum(len(cm.bits) for cm in cms.values()) == kinds["clkmux"],
          "all %d bits CLK.AA.I/CLK.II.I belong to one of the two muxes" % kinds["clkmux"])
    # bit 5 switches in a source at bits 0-4 (active 0); no bit: the default setting; ACLK: oscillator bits 6+7
    shape = all(c == (1 << len(cm.bits)) - 1 or (1 << len(cm.bits)) - 1 - c in [0x20 | 1 << i for i in range(5)]
                for cm in cms.values() for c in cm.codes if cm.sources[cm.codes[c]].kind != "osc")
    check(shape, "every source except the default setting: bit 5 and exactly one of bits 0-4 programmed")
    used = {}
    for f in sources.XACT_BITSTREAMS:
        r = bitstream.read(f).raw
        for name, cm in cms.items():
            c = iobmux.code(cm.bits, r)
            if c != (1 << len(cm.bits)) - 1:
                used[f.split("/")[-1] + " " + name] = c
    check(not used, "no XACT bitstream uses a clock buffer (both muxes in the default setting) %s" % (used or ""))
    check(len(cms["CLK.AA.I"].codes) == 6 and len(cms["CLK.II.I"].codes) == 7 and
          {s for p, s, _ in g.unmodelled if p in cms} == {"@osc"},
          "in the graph: GCLK from 6 sources, ACLK from 6 (the oscillator has no Bel)")

    print("TEST1.LCA (XACT) against TEST1.RBT")
    nets = lca.parse()
    raw = bitstream.read(sources.TEST1_RBT).raw
    db = config.Database()
    items, problems = config.decode(db, raw)
    missing, count, kmux = lca.check_elements(nets, items, db)
    n = sum(count.values())
    decoded_k = ["%s %s" % (it.name, it.value) for it in items if it.kind == "mux" and it.name == "P9.K"]
    check(not missing, "all %d routing elements from XACT appear in the decoding (%d of them at the clock of "
          "latched IOBs, not checked: XACT names %s, decoded %s; %d T inputs with buffer off/on) %s"
          % (n, count["iob-k"], " and ".join(kmux), decoded_k[0], count["mux-mode"],
             dict(missing) if missing else ""))
    skip = {it.name for it in items if it.kind == "mux" and it.name.endswith(".T") and it.value in ("off", "on")}
    res = lca.check_nets(nets, g, raw, skip)
    ok = [r[0] for r in res if r[2] == "ok" and len(r[1]) > 1]
    bad = [r for r in res if r[2] not in ("ok", "no CLB pins", "separated")]
    split = [r[0] for r in res if r[2] == "separated"]
    check(not bad and set(split) <= {"CB", "DB"},
          "the graph connects the pins of the nets %s like XACT and separates all nets (XACT did not route "
          "CB, DB) %s %s" % (" ".join(ok), bad or "", [r[:2] for r in res if r[2] == "separated"]))
    lb = lca.parse_blocks()
    bad = lca.check_blocks(lb, items)
    check(not bad, "Base, Config and Equate of all %d blocks (%d CLBs, %d IOBs) match the decoding %s"
          % (len(lb), sum(1 for b in lb.values() if b["base"] != "IO"),
             sum(1 for b in lb.values() if b["base"] == "IO"), bad or ""))

    print("Encoding (config.encode) against all XACT bitstreams")
    diffs = {}
    for f in sources.XACT_BITSTREAMS:
        r = bitstream.read(f).raw
        r2 = config.encode(db, config.parse_text(config.format_text(config.decode(db, r)[0])))
        diffs[f.split("/")[-1]] = sum(1 for a, b in zip(r, r2) if a != b)
    check(not any(diffs.values()), "text -> bits reproduces each of the %d bitstreams bit-exactly %s"
          % (len(diffs), {k: v for k, v in diffs.items() if v} or ""))

    print("Repowering buffers (bidi bits) against all XACT bitstreams")
    gs = graph.Graph(entries, lines, split_bidi=True)
    nv = sum(1 for b in gs.buffers if b.line.startswith("col."))
    check(len(gs.buffers) == 158 and nv == 86 and
          {b.g for b in gs.buffers if b.line.startswith("col.")} == {52, 109} and
          {b.g for b in gs.buffers if b.line.startswith("row.")} == {65, 125},
          "158 buffers on the single-length segments at the section boundaries: %d vertical above rows D and G, "
          "%d horizontal before columns D and G" % (nv, len(gs.buffers) - nv))
    total, bad = 0, []
    for f in sources.XACT_BITSTREAMS:
        ok, b = gs.bidi_check(bitstream.read(f).raw)
        total += ok
        bad += [(f.split("/")[-1],) + x for x in b]
    check(not bad and total >= 18, "direction of every used buffer: bit 0 drives down or right, bit 1 "
          "up or left (%d buffers in TEST1.RBT and AND_OR.BIT) %s" % (total, bad or ""))

    print("Packages (xc2064db.packages, Data Books 1993/1994)")
    all_pads = [p[0] for p in iobmux.pads()]
    counts = {}
    for pkg in packages.PACKAGES:
        m = packages.pads(pkg, all_pads)
        counts[pkg] = len(m)
        check(set(m.values()) <= set(all_pads) and len(set(m.values())) == len(m),
              "%s: %d pins, each on its own pad from iob.js" % (pkg, len(m)))
    check(counts == {"PC68": 58, "PD48": 40, "PC44": 34, "PG68": 57},
          "number of user I/Os: PC68 58, PD48 40, PC44 34, PG68 57 (without P43, PGA pin unknown)")

    decoded = sum(n for k, n in kinds.items() if k != "unused")
    print("Coverage of the %d used bits:" % (bitmap.NBITS - kinds["unused"]))
    print("  decoded (pips, switch matrices, muxes of CLBs, IOBs and clock buffers, buffer direction, CLB and "
          "IOB configuration, options): %d" % decoded)
    if failed:
        print("%d cross-checks failed" % len(failed))
        return 1
    return 0


sys.exit(main())
