"""Gegenprobe mit Shirriffs Bitstream-Decoder: seine Skripte (external/shirriff-xc2064/html: draw.js,
karnaugh.js, parse.js, iob.js, clb.js) laufen ohne Browser in QuickJS (Python-Paket quickjs), dekodieren eine
RBT-Datei mit seinem eigenen Leser, und das Ergebnis wird mit der eigenen Dekodierung (config.decode, Tabellen
aus iobmux/clbmux) verglichen.

Unabhängig ist vor allem das Innere der CLBs: Shirriff liest Wahrheitstabellen, Eingangsauswahl, Basis, X/Y,
Speicherelement, Set/Reset und Takt direkt aus der Bit-Tabelle in Chip-Lage (eigene Bitreihenfolge der LUTs),
das Paket über die Namen der Bitkarte. Die Muxe von CLB und IOB (Codes und Quellen) hat das Paket aus clb.js und
iob.js übernommen; der Vergleich prüft hier die Übernahme (Code -> Quelle, G-Lage der Kreuzung). Pips,
Switch-Verbindungen und Bidi-Bits lesen beide aus denselben Einträgen der Bitkarte (Namen der Matrizen
verschieden, siehe unten).

Bekannte Abweichungen, die der Vergleich berücksichtigt:
  - Takt K oder G: Shirriff unterscheidet nach dem Bit CLK Invert, das Paket nach der Belegung des K-Mux (mit
    TEST1.LCA belegt). Verglichen wird nur aus / über C (mit Umkehrung) / über K oder G.
  - Switch-Matrizen der Zeile I: Shirriffs Klasse Switch vertauscht dort 8.1 und 8.2 (XACT benennt wie das
    Paket).
  - Bei Basis F und FGM liegt derselbe Ausgang an F und G; Shirriff nennt ihn F bzw. M, das Paket F und G.
"""
import json
import os

from . import blocks, config, iobmux, sources

JS_FILES = ("draw.js", "karnaugh.js", "parse.js", "iob.js", "clb.js")

# Was die Skripte vom Browser brauchen, ohne Wirkung (Zeichnen und Seite werden nicht benutzt)
STUBS = r"""
var window = {};
var debug = false;
var console = {log: function () {}};
function alert(msg) { throw new Error("alert: " + msg); }
function assert(cond, msg) { if (!cond) throw new Error("assert: " + msg); }
function $() {
  var o = {};
  ["css", "text", "html", "width", "height", "append", "on", "click"].forEach(function (k) { o[k] = function () { return o; }; });
  return o;
}
$.get = function () {};
"""

# Bitkarte laden wie loadConfig(), dekodieren wie rbtUpload(), Ergebnis als JSON
DRIVER = r"""
function shirriffLoadDefs(text) {
  text.split(/\r?\n/).forEach(function (l) {
    var m = l.match(/Bit:\s+(\S+)\s+(.*)/);
    if (m) config[parseInt(m[1], 16)] = m[2];
  });
  initParser();
}

function shirriffDecode(rbtText) {
  rawBitstream = parseRbtFile(rbtText);
  bitstreamTable = makeBitstreamTable(rawBitstream);
  decode(rawBitstream, config);
  var clbs = {};
  Object.entries(clbDecoders.clbDecoders).forEach(function ([tile, d]) {
    if (!d.clbInternal) return; // CLK.AA.I, CLK.II.I
    var c = d.clbInternal;
    d.generateClbPips(tile);
    var mux = {};
    [["A", d.apips], ["B", d.bpips], ["C", d.cpips], ["D", d.dpips], ["K", d.kpips]].forEach(function ([pin, l]) {
      var s = l.filter(function (p) { return p[4]; });
      mux[pin] = s.length ? s[0][0] : null;
    });
    clbs[tile] = {base: c.configBase, f: c.configF, g: c.configG, nf: c.configNf, ng: c.configNg, x: c.configX,
                  y: c.configY, q: c.configQ, clk: c.configClk, set: c.configSet, res: c.configRes, mux: mux};
  });
  var iobs = {};
  Object.entries(iobDecoders.iobsFromPin).forEach(function ([pin, iob]) {
    var sel = function (l) {
      if (!l) return null;
      for (var i = 0; i < l.length; i++) if (l[i][4]) return [i, l[i][0], l[i][3]];
      return null;
    };
    iobs[pin] = {latch: iob.latch, tmode: iob.tmode, o: sel(iob.opips), t: sel(iob.tpips), k: sel(iob.kpips)};
  });
  var pips = Object.entries(pipDecoder.entries).filter(function ([g, b]) { return b == 0; }).map(function ([g]) { return g; });
  var switches = [];
  Object.entries(switchDecoders.switches).forEach(function ([name, sw]) {
    sw.wires.forEach(function ([a, b]) { switches.push([name, a, b]); });
  });
  var bidi = Object.entries(bidiDecoder.entries).filter(function ([g, b]) { return b == 0; }).map(function ([g]) { return g; });
  return JSON.stringify({clbs: clbs, iobs: iobs, pips: pips, switches: switches, bidi: bidi});
}
"""


class Decoder:
    """Shirriffs Decoder in einem QuickJS-Kontext (einmal laden, beliebig oft dekodieren)"""

    def __init__(self):
        import quickjs  # Python-Paket "quickjs" (.devcontainer/requirements.txt)
        self.ctx = quickjs.Context()
        self.ctx.eval(STUBS)
        html = os.path.join(sources.SHIRRIFF, "html")
        for f in JS_FILES:
            self.ctx.eval(sources.read_text(os.path.join(html, f)))
        self.ctx.eval(DRIVER)
        self.ctx.set("defsText", sources.read_text(sources.DEF_TXT))
        self.ctx.eval("shirriffLoadDefs(defsText)")

    def decode(self, rbt_text):
        """RBT-Text -> dict (clbs, iobs, pips, switches, bidi)"""
        self.ctx.set("rbtText", rbt_text)
        return json.loads(self.ctx.eval("shirriffDecode(rbtText)"))


def available():
    try:
        import quickjs  # noqa: F401
        return True
    except ImportError:
        return False


# --- Vergleich -------------------------------------------------------------------------------------
def _merged(base):
    """Bei Basis F und FGM liegt an F und G derselbe Ausgang"""
    return base in ("F", "FGM")


def _out(v, base):
    """Ausgang (X, Y, Set-, Reset-Quelle) einheitlich: F/G/M bei verbundenem Ausgang als M"""
    return "M" if _merged(base) and v in ("F", "G", "M") else v


def _clk_ours(v):
    """Takt des Pakets -> (Art, umgekehrt): aus, C (mit NOT), KG (K oder G, Umkehrung nicht vergleichbar)"""
    p = v.split(":") if v else []
    if not p or p[0] in ("NOT", "OFF"):
        return ("aus", None)
    if p[0] == "C":
        return ("C", "NOT" in p)
    return ("KG", None)


def _clk_shirriff(v, base):
    p = v.split(":") if v else []
    if not p or p[0] == "NOT":
        return ("aus", None)
    if p[0] == "C":
        return ("C", "NOT" in p)
    return ("KG", None)


def compare(db, raw, sh):
    """Shirriffs Dekodierung sh (Decoder.decode) gegen die eigene von raw. Ergebnis: (Zähler, Abweichungen)"""
    items, problems = config.decode(db, raw)
    if problems:
        return {}, ["eigene Dekodierung: %s" % p for p in problems[:5]]
    bad, n = [], {}
    clb = {it.name: blocks.parse_fields(it.value) for it in items if it.kind == "clb"}

    # CLB: Inneres
    for t, f in sorted(clb.items()):
        s = sh["clbs"][t]
        base = f["BASE"]
        diff = []
        if s["base"] != base:
            diff.append("Basis %s/%s" % (base, s["base"]))
        sf = s["f"].split(":")
        if base == "F":  # Shirriff: Eingang 1, B, Eingang 2, Eingang 3
            sf = [sf[0], sf[2], sf[3]]
        if sf != f["F"].split(":"):
            diff.append("F-Eingänge %s/%s" % (f["F"], s["f"]))
        if base != "F" and s["g"] != f["G"]:
            diff.append("G-Eingänge %s/%s" % (f["G"], s["g"]))
        if s["nf"] != int(f["LUTF"], 16) or s["ng"] != int(f["LUTG"], 16):
            diff.append("Tabellen %s %s / %02X %02X" % (f["LUTF"], f["LUTG"], s["nf"], s["ng"]))
        for k, sk in (("X", "x"), ("Y", "y"), ("SET", "set"), ("RES", "res")):
            if _out(f[k], base) != _out(s[sk], base):
                diff.append("%s %s/%s" % (k, f[k], s[sk]))
        if f["Q"] != s["q"]:
            diff.append("Q %s/%s" % (f["Q"], s["q"]))
        if _clk_ours(f["CLK"]) != _clk_shirriff(s["clk"], base):
            diff.append("Takt %s/%s" % (f["CLK"], s["clk"]))
        if diff:
            bad.append("CLB %s: %s" % (t, ", ".join(diff)))
    n["CLBs"] = len(clb)

    # CLB-Eingangs-Muxe: G-Lage der gewählten Kreuzung
    cnt = 0
    for name, m in sorted(db.muxes.items()):
        code, src = m.decode(raw)
        tile, pin = name.split(".")
        g = sh["clbs"][tile]["mux"][pin]
        ours = src.g if src else None
        cnt += 1
        if ours != g:
            bad.append("Mux %s: %s (%s) / %s" % (name, src.line if src else "none", ours, g))
    n["CLB-Eingänge"] = cnt

    # IOBs: Eingang gelatcht, O-, T- und K-Mux (Index in der Liste aus iob.js, bei Leitungen auch die G-Lage)
    latched = {it.name: blocks.parse_fields(it.value)["I"] == "Q" for it in items if it.kind == "iob"}
    cnt = 0
    for pin, iob in sorted(db.iobs.items(), key=lambda kv: int(kv[0][1:])):
        s = sh["iobs"][pin]
        cnt += 1
        if bool(s["latch"]) != latched[pin]:
            bad.append("IOB %s: gelatcht %s/%s" % (pin, latched[pin], s["latch"]))
        c = iobmux.code(iob.obits, raw)
        _cmp_sel(bad, pin + ".O", iob.o, iob.omux.get(c), s["o"])
        c = iobmux.code(iob.tbits, raw)
        if c == iob.t_off or c == iob.t_on:
            want = "" if c == iob.t_off else "ON"
            if s["tmode"] != want:
                bad.append("IOB %s.T: %s/%s" % (pin, "off" if want == "" else "on", s["tmode"]))
        else:
            if s["tmode"] != "TRI":
                bad.append("IOB %s.T: Tristate/%s" % (pin, s["tmode"]))
            _cmp_sel(bad, pin + ".T", iob.t, iob.tmux.get(c), s["t"])
    for pin, km in sorted(db.kmuxes.items()):
        _cmp_sel(bad, pin + ".K", km.sources, km.codes.get(iobmux.code(km.bits, raw)), sh["iobs"][pin]["k"])
    n["IOBs"] = cnt
    n["K-Muxe"] = len(db.kmuxes)

    # Pips, Switch-Verbindungen, Puffer: dieselben Bits, Namen der Matrizen verglichen
    ours_pips = {e.key[0] for e in db.entries if e.kind == "pip" and raw[e.index] == 0}
    if ours_pips != set(sh["pips"]):
        bad.append("Pips: nur hier %s, nur bei Shirriff %s" % (sorted(ours_pips - set(sh["pips"]))[:5],
                                                              sorted(set(sh["pips"]) - ours_pips)[:5]))
    n["Pips"] = len(ours_pips)
    ours_sw = {"%s %s" % (it.name, it.value) for it in items if it.kind == "switch"}
    sh_sw = set()
    for name, a, b in sh["switches"]:
        if name[0] == "I":  # Zeile I: Shirriff vertauscht 8.1 und 8.2
            name = name[:-1] + {"1": "2", "2": "1"}[name[-1]]
        sh_sw.add("%s %d-%d" % (name, min(a, b), max(a, b)))
    if ours_sw != sh_sw:
        bad.append("Switch-Verbindungen: nur hier %s, nur bei Shirriff %s" % (sorted(ours_sw - sh_sw)[:5],
                                                                             sorted(sh_sw - ours_sw)[:5]))
    n["Switch-Verbindungen"] = len(ours_sw)
    ours_bidi = {e.key[0] for e in db.entries if e.kind == "bidi" and raw[e.index] == 0}
    if ours_bidi != set(sh["bidi"]):
        bad.append("Bidi: %d/%d" % (len(ours_bidi), len(sh["bidi"])))
    return n, bad


def _cmp_sel(bad, name, entries, idx, s):
    """Gewählte Quelle eines IOB-Mux: Index in der Liste, bei einer Leitung auch die G-Lage"""
    if idx is None and s is None:
        return
    if idx is None or s is None or idx != s[0]:
        bad.append("IOB %s: Quelle %s/%s" % (name, idx, s and s[0]))
        return
    ent = entries[idx]
    if ent.kind == "route" and ent.g != s[1]:
        bad.append("IOB %s: %s bei %s, Shirriff %s (%s)" % (name, ent.line, ent.g, s[1], s[2]))


def rbt_text(path):
    """Text einer RBT-Datei; .BIT (binär) wird über bitstream.write_rbt in die Textform gebracht"""
    from . import bitstream
    if path.upper().endswith(".RBT"):
        return sources.read_text(path)
    return bitstream.write_rbt(bitstream.read(path).raw, os.path.splitext(os.path.basename(path))[0], "2064PC68")
