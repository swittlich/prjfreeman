"""Abdeckungsbericht und Gegenproben der Datenquellen:  python3 -m xc2064db  (in arch/xc2064)

Endet mit Fehler, wenn eine Gegenprobe scheitert. Abdeckung: welche Bits das Paket dekodiert (seit die
Codes der Taktpuffer-Eingänge bekannt sind, alle benutzten).
"""
import collections
import csv
import re
import sys

from . import bitmap, bitstream, clbmux, config, graph, iobmux, lca, packages, sources, switches
from .lines import Lines

failed = []


def check(ok, text):
    print("  [%s] %s" % ("ok" if ok else "FEHLER", text))
    if not ok:
        failed.append(text)


def openxc_pattern():
    """possible_connections aus openxc2064 (8x8-Matrix, Pins 0-7) als Pin-Paare 1-8"""
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

    print("Bitkarte %s" % sources.DEF_TXT)
    print("  %s" % ", ".join("%s %d" % kv for kv in sorted(kinds.items(), key=lambda kv: -kv[1])))
    check(not bitmap.duplicates(entries), "jeder Name in der Bitkarte ist eindeutig (Textformat 'bit ...')")
    print("  Hinweis: Bits %s fehlen in der Datei, gelten als unbenutzt" % bitmap.missing(entries))

    print("Leitungen (draw.js): %d Spalten-, %d Zeilennamen" % (len(lines.col_name), len(lines.row_name)))
    pips = [e for e in entries if e.kind == "pip"]
    unresolved = [e.key[0] for e in pips if lines.pip_name(e.key[0]) is None]
    check(not unresolved, "alle %d PIPs liegen auf der Kreuzung zweier benannter Leitungen %s"
          % (len(pips), unresolved[:5]))

    conn = switches.connections(entries, lines)
    pats = switches.patterns(conn)
    print("Switch-Matrizen: %d mit Magic-Bits, %d Muster" % (len(conn), len(pats)))
    for pat, names in sorted(pats.items(), key=lambda kv: -len(kv[1])):
        print("  %3d x %2d Verbindungen: %s" % (len(names), len(pat), " ".join("%d-%d" % p for p in pat)))
    interior = max(pats, key=lambda p: len(pats[p]))
    check(len(conn) == 154 and len(pats[interior]) == 98, "154 Matrizen, davon 98 mit dem inneren Muster")
    check(all(set(p) <= set(interior) for p in pats), "jedes Randmuster ist ein Teil des inneren Musters")
    ox, symmetric = openxc_pattern()
    check(symmetric and ox == set(interior),
          "openxc2064 possible_connections (Pins 0-7) = inneres Muster aus den Magic-Bits (Pins 1-8)")

    muxes = clbmux.muxes(lines, entries)
    nbits = sum(len(m.bits) for m in muxes.values())
    per_pin = collections.defaultdict(set)
    for m in muxes.values():
        per_pin[m.pin].add(len(m.sources))
    print("CLB-Eingangs-Muxe (clb.js): %d Muxe, %d Bits; Quellen je Eingang %s" % (
        len(muxes), nbits, ", ".join("%s %s" % (p, "-".join(map(str, sorted(v)))) for p, v in sorted(per_pin.items()))))
    check(nbits == kinds["clbmux"], "alle %d CLB-Mux-Bits der Bitkarte gehören zu einem Mux" % kinds["clbmux"])
    check(all(len(set(v for v in m.codes.values() if v is not None)) == len(m.sources) for m in muxes.values()),
          "jede Quelle hat genau einen Code (Quelle -> Bits eindeutig, für xc2064pack)")

    print("openxc2064 %s" % sources.OPENXC)
    check(sources.text_sha1(sources.OPENXC_DEF_TXT) == sources.text_sha1(sources.DEF_TXT),
          "pin_planning/XC2064-def.txt ist eine Kopie von Shirriffs Datei (keine unabhängige Quelle)")
    rows = list(csv.reader(sources.read_text(sources.OPENXC_CSV).splitlines()))
    same = all(rows[i % bitmap.FRAME_BITS][i // bitmap.FRAME_BITS].strip() == e.text
               for i, e in enumerate(entries) if e.text != "(fehlt)")
    check(len(rows) == bitmap.FRAME_BITS and same,
          "XC2064-spreadsheet.csv ist dieselbe Bitkarte, nur als 71 x 160 Tabelle")

    print("Routing-Graph (xc2064db.graph)")
    g = graph.Graph(entries, lines)
    kc = collections.Counter(c.kind for c in g.conns)
    print("  %s" % ", ".join("%s %d" % kv for kv in sorted(kc.items())))
    check(not g.skipped, "jedes PIP-Bit gehört zu einer Verbindung des Graphen %s" % list(g.skipped)[:4])
    print("  nicht modelliert (iob.js): %s" % ", ".join("%s %s" % (p, s) for p, s, _ in g.unmodelled))

    print("Eingänge der Taktpuffer (iobmux.clkmuxes, Codes aus MAKEBITS)")
    cms = iobmux.clkmuxes(lines, entries)
    for name, cm in sorted(cms.items()):
        print("  %s (%s): %s" % (name, cm.net, ", ".join("%d %s" % (c, iobmux.source_name(cm.sources[k]))
                                                          for c, k in sorted(cm.codes.items(), reverse=True))))
    check(sum(len(cm.bits) for cm in cms.values()) == kinds["clkmux"],
          "alle %d Bits CLK.AA.I/CLK.II.I gehören zu einem der beiden Muxe" % kinds["clkmux"])
    # Bit 5 schaltet eine Quelle an Bit 0-4 zu (aktiv 0); ohne Bit die Grundstellung, ACLK: Oszillator Bits 6+7
    shape = all(c == (1 << len(cm.bits)) - 1 or (1 << len(cm.bits)) - 1 - c in [0x20 | 1 << i for i in range(5)]
                for cm in cms.values() for c in cm.codes if cm.sources[cm.codes[c]].kind != "osc")
    check(shape, "jede Quelle außer der Grundstellung: Bit 5 und genau eines der Bits 0-4 programmiert")
    used = {}
    for f in sources.XACT_BITSTREAMS:
        r = bitstream.read(f).raw
        for name, cm in cms.items():
            c = iobmux.code(cm.bits, r)
            if c != (1 << len(cm.bits)) - 1:
                used[f.split("/")[-1] + " " + name] = c
    check(not used, "kein XACT-Bitstream benutzt einen Taktpuffer (beide Muxe in Grundstellung) %s" % (used or ""))
    check(len(cms["CLK.AA.I"].codes) == 6 and len(cms["CLK.II.I"].codes) == 7 and
          {s for p, s, _ in g.unmodelled if p in cms} == {"@osc"},
          "im Graphen: GCLK aus 6 Quellen, ACLK aus 6 (der Oszillator hat kein Bel)")

    print("TEST1.LCA (XACT) gegen TEST1.RBT")
    nets = lca.parse()
    raw = bitstream.read(sources.TEST1_RBT).raw
    db = config.Database()
    items, problems = config.decode(db, raw)
    missing, count, kmux = lca.check_elements(nets, items, db)
    n = sum(count.values())
    decoded_k = ["%s %s" % (it.name, it.value) for it in items if it.kind == "mux" and it.name == "P9.K"]
    check(not missing, "alle %d Routing-Elemente von XACT stehen in der Dekodierung (davon %d am Takt gelatchter "
          "IOBs, nicht geprüft: XACT nennt %s, dekodiert %s; %d T-Eingänge mit Puffer aus/an) %s"
          % (n, count["iob-k"], " und ".join(kmux), decoded_k[0], count["mux-mode"],
             dict(missing) if missing else ""))
    skip = {it.name for it in items if it.kind == "mux" and it.name.endswith(".T") and it.value in ("off", "on")}
    res = lca.check_nets(nets, g, raw, skip)
    ok = [r[0] for r in res if r[2] == "ok" and len(r[1]) > 1]
    bad = [r for r in res if r[2] not in ("ok", "ohne CLB-Pins", "getrennt")]
    split = [r[0] for r in res if r[2] == "getrennt"]
    check(not bad and set(split) <= {"CB", "DB"},
          "der Graph verbindet die Pins der Netze %s wie XACT und trennt alle Netze (CB, DB hat XACT "
          "nicht geroutet) %s %s" % (" ".join(ok), bad or "", [r[:2] for r in res if r[2] == "getrennt"]))
    lb = lca.parse_blocks()
    bad = lca.check_blocks(lb, items)
    check(not bad, "Base, Config und Equate aller %d Blöcke (%d CLBs, %d IOBs) passen zur Dekodierung %s"
          % (len(lb), sum(1 for b in lb.values() if b["base"] != "IO"),
             sum(1 for b in lb.values() if b["base"] == "IO"), bad or ""))

    print("Kodierung (config.encode) gegen alle XACT-Bitstreams")
    diffs = {}
    for f in sources.XACT_BITSTREAMS:
        r = bitstream.read(f).raw
        r2 = config.encode(db, config.parse_text(config.format_text(config.decode(db, r)[0])))
        diffs[f.split("/")[-1]] = sum(1 for a, b in zip(r, r2) if a != b)
    check(not any(diffs.values()), "Text -> Bits gibt jeden der %d Bitstreams bitgenau wieder %s"
          % (len(diffs), {k: v for k, v in diffs.items() if v} or ""))

    print("Repowering-Puffer (Bidi-Bits) gegen alle XACT-Bitstreams")
    gs = graph.Graph(entries, lines, split_bidi=True)
    nv = sum(1 for b in gs.buffers if b.line.startswith("col."))
    check(len(gs.buffers) == 158 and nv == 86 and
          {b.g for b in gs.buffers if b.line.startswith("col.")} == {52, 109} and
          {b.g for b in gs.buffers if b.line.startswith("row.")} == {65, 125},
          "158 Puffer auf den Einzelsegmenten an den Sektionsgrenzen: %d senkrecht über den Zeilen D und G, "
          "%d waagerecht vor den Spalten D und G" % (nv, len(gs.buffers) - nv))
    total, bad = 0, []
    for f in sources.XACT_BITSTREAMS:
        ok, b = gs.bidi_check(bitstream.read(f).raw)
        total += ok
        bad += [(f.split("/")[-1],) + x for x in b]
    check(not bad and total >= 18, "Richtung jedes benutzten Puffers: Bit 0 treibt nach unten bzw. rechts, Bit 1 "
          "nach oben bzw. links (%d Puffer in TEST1.RBT und AND_OR.BIT) %s" % (total, bad or ""))

    print("Gehäuse (xc2064db.packages, Data Books 1993/1994)")
    all_pads = [p[0] for p in iobmux.pads()]
    counts = {}
    for pkg in packages.PACKAGES:
        m = packages.pads(pkg, all_pads)
        counts[pkg] = len(m)
        check(set(m.values()) <= set(all_pads) and len(set(m.values())) == len(m),
              "%s: %d Pins, jeder auf einem eigenen Pad aus iob.js" % (pkg, len(m)))
    check(counts == {"PC68": 58, "PD48": 40, "PC44": 34, "PG68": 57},
          "Anzahl Benutzer-I/O: PC68 58, PD48 40, PC44 34, PG68 57 (ohne P43, PGA-Pin unbekannt)")

    decoded = sum(n for k, n in kinds.items() if k != "unused")
    print("Abdeckung der %d benutzten Bits:" % (bitmap.NBITS - kinds["unused"]))
    print("  dekodiert (Pips, Switch-Matrizen, Muxe von CLB, IOB und Taktpuffern, Puffer-Richtung, CLB- und "
          "IOB-Konfiguration, Optionen): %d" % decoded)
    if failed:
        print("%d Gegenproben fehlgeschlagen" % len(failed))
        return 1
    return 0


sys.exit(main())
