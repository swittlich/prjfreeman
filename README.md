# Architektur `xc2064`: Modell des Xilinx XC2064

Der XC2064 (1985) war das erste FPGA: 64 Configurable Logic Blocks (CLBs) in einem 8×8-Raster und
58 I/O-Pins (PLCC68). Diese Architektur bildet ihn als nextpnr-Himbächel-uarch nach, mit yosys-Plugin,
Place & Route, Timing und einer vollständigen Schaltplan-Ansicht in der GUI. Aus dem Ergebnis macht
`tools/xc2064pack` einen Bitstream (RBT im Format von XACT, siehe [Bitstream](#bitstream)); auf einem
echten Chip geladen ist noch keiner.

Grundlagen:
- XC2000-Datenblatt
- Ken Shirriff, [Reverse-engineering the first FPGA chip, the XC2064](https://www.righto.com/2020/09/reverse-engineering-first-fpga-chip.html)
- sein Bitstream-Decoder [shirriff/xc2064](https://github.com/shirriff/xc2064), aus dessen `clb.js` und `iob.js`
  die Eingangsmultiplexer der CLBs, die Optionen des Speicherelements, die Pad-Tabelle und die
  Multiplexer und PIPs der IOBs stammen; der Decoder selbst läuft ohne Browser als Gegenprobe
  (`tools/xc2064shirriff`, siehe [Regressionstest](#regressionstest))
- [rates37/openxc2064](https://github.com/rates37/openxc2064) mit Bitstreams aus Xilinx' XACT
- Xilinx *The Programmable Logic Data Book* 1994 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1994_Xilinx_Programmable_Logic_Data_Book.pdf)),
  XC2000-Abschnitt S. 2-216 bis 2-222: Lieferformen und die Timing-Tabellen von CLB und IOB (-70, -100, -130)
- dasselbe von 1993 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1993_Xilinx_Programmable_Logic_Data_Book.pdf)),
  S. 2-208 bis 2-214: dieselben Tabellen mit -50, -70 und -100
- `MAKEBITS` aus Xilinx XACT 5.2.0 als Blackbox (in DOSBox, außerhalb des Repos): Codes der
  Taktpuffer-Eingänge und Gegenprobe für `xc2064pack` (siehe [Taktpuffer](#taktpuffer-eingänge-makebits))

Beide Repos sind Submodules unter `arch/xc2064` (siehe [Datenquellen](#datenquellen-und-bitstream-werkzeuge)):

```bash
git submodule update --init arch/xc2064/shirriff-xc2064 arch/xc2064/openxc2064
```

## Was nachgebildet ist

| Element | Modell | Quelle / Abweichung |
|---|---|---|
| Raster | 8×8 CLBs (X1Y1…X8Y8) plus IO-Ring. Shirriffs 9×9 Kacheln AA…II entsprechen X1Y1…X9Y9. Jede Kachel enthält die Kanäle oberhalb und links ihrer CLB, die 9. Spalte/Zeile nur Routing und Pads | Shirriff |
| Routing-Graph | Aus den Daten gebaut (`xc2064db.graph`): jeder Pip ist ein PIP-Bit, ein Magic-Bit einer Switch-Matrix oder ein Mux-Code eines CLB-Eingangs bzw. eines IOB-Multiplexers, die Leitungen tragen Shirriffs bzw. XACTs Namen. Auch die Eingänge der beiden Taktpuffer sind Mux-Codes | `XC2064-def.txt`, `draw.js`, `clb.js`, `iob.js`, Taktpuffer-Codes aus `MAKEBITS`; geprüft mit `TEST1.LCA` (siehe [Datenquellen](#datenquellen-und-bitstream-werkzeuge)) |
| Switch-Matrizen | 2 je Kreuzung (8.1, 8.2), an den vier Ecken keine, 8 Pins. Innen 20 Verbindungen nach dem Muster der Magic-Bits (jeder Pin mit 5 der 7 anderen), am Rand dasselbe ohne die Pins der fehlenden Seite. 8.1 verbindet senkrecht local.1/2, 8.2 local.3/4 mit je zwei waagerechten Leitungen (in Zeile I gespiegelt) | Magic-Bits; Datenblatt Bild 7b; Gegenprobe `possible_connections` (openxc2064) |
| Einzelsegmente | Senkrecht local.1-4 von Matrix zu Matrix und die fünfte Leitung local.5, waagerecht 4 (innen local.1/3/4/5, am Rand local.1-4) | Datenblatt *General-Purpose Interconnect*: 5 senkrechte, 4 waagerechte Segmente je eine Blocklänge |
| Repowering-Puffer | 158, je einer auf jedem Einzelsegment, das eine Grenze der 9 Sektionen kreuzt: senkrecht kurz vor dem Kanal der Zeilen D und G, waagerecht vor dem der Spalten D und G. Ein Bit wählt die Richtung (0: nach unten bzw. rechts, 1: nach oben bzw. links), aus ist er nie. Deshalb trennt er das Segment im Routing-Graphen nicht; die Richtung folgt aus dem Routing (`xc2064db.graph.bidi_bit`), wie bei XACT | Bidi-Bits der Bitkarte (G-Lage = Leitung); Richtung belegt mit `TEST1.RBT` und `AND_OR.BIT` (18 Puffer, kein Widerspruch); Datenblatt *Interconnect* |
| Fünfte senkrechte Leitung | Läuft an keiner Matrix vorbei. Ihr Stück der Zeile R beginnt an einem Verbindungspunkt oben im Kanal (`row.R.local.0`), kreuzt dort local.3/4 auf der Spur von local.6, knickt auf die Spur von local.5, läuft an der CLB vorbei (B, C, Y) und kreuzt im Kanal darunter noch local.0, local.3 und local.4 | Datenblatt Bild 7b (gestrichelt); belegt durch Netz `p1` in `TEST1.LCA` |
| Funktionsgeneratoren | `F`, `G` (Primitiv `XC2000_LUT3`): Eingang 1 aus {A, B}, Eingang 2 aus {B, C}, Eingang 3 aus {C, D, **Q**} | `clb.js` |
| 4-Variablen-Modus | `FG` (`XC2000_LUT4`): Eingänge wie F/G, **B** wählt zwischen F und G (I[3]), belegt beide | `clb.js` |
| Mux-Modus | `FGM` (`XC2000_FGM`): F und G mit **eigenen** Eingängen (`F[2:0]`, `G[2:0]`), **B** (`S`) wählt (1: F), der Ausgang M liegt an F und G. In den Bits derselbe Modus wie FG, nur stehen die Eingangs-Muxe von F und G verschieden. Er lohnt sich nur mit der Rückführung Q: F liest D, G das eigene Q (oder umgekehrt), also eine Funktion von 5 Signalen `S ? f(a, c, x) : g(a, c, Q)`. Der Pass `xc2064_fgm` bildet sie aus LUTs vor einem FF | Data Book 1993, *CLB Combinatorial Logic Options* (S. 2-182/2-183, „Option 3“, „D und Q nie in derselben Funktion“); `clb.js`; `TEST1.LCA` (CLB AA, dort ohne benutzte Ausgänge) |
| Speicherelement | `XC2000_DFF`: Flipflop oder **Latch** (`LATCH`), Takt aus **K, C oder G**, **invertierbar** (`CLKINV`), asynchrones **Set aus A oder F**, **Reset aus D oder G**, Daten aus F bzw. FG | `clb.js`; Vorrang Reset vor Set angenommen |
| Ausgänge | X, Y je aus Q, F oder G, beide in den senkrechten Kanal **rechts** der CLB: X (Zeile io6) auf local.2, local.4 und long.1, Y (Zeile y) auf local.1, local.3, local.5 und long.2. In Spalte H liegen die Kreuzungen im Randkanal: X (auf Höhe der Zeile b) auf local.2, local.4 und long.2, Y auf local.1, local.3, long.1 und long.3 | PIP-Bits der Bitkarte |
| CLB-Eingänge | Alle Quellen aus `clb.js` mit ihren Mux-Codes: A 6–7 (Kanal oben, long.1, X von oben), B 10 (local.1-5, Y von links, long.1/2, GCLK, X von oben), C 8 (local.1-5, long.1/2, X von unten), D 6–7 (Kanal unten, long.1, X von unten), K 2 (long.2, GCLK); am Rand andere Leitungen und Pads | `clb.js`; mit allen XACT-Bitstreams und `TEST1.RBT` geprüft |
| Direktverbindungen | X fest auf A/B der CLB darunter und C/D der CLB darüber, Y fest auf B der CLB rechts (Spur local.6). Am Rand übernehmen Pads diese Quellen | Datenblatt *Direct Interconnect* und Bild 9; Quellen in `clb.js` |
| Long Lines | Senkrecht 2 je Spalte (Spalte A: long.2–4, Spalte I: long.1–3), waagerecht 1 je Zeile (Zeile A: long.2/3, Zeile I: long.1/2) | Datenblatt *Longlines*: zusätzliche Long Line neben jeder IOB-Reihe |
| Taktnetze | GCLK (`CLK.AA.O` oben und `col.*.clk` je Spalte) auf B und K jeder CLB, ACLK (`row.I.clk` unten) über PIPs auf die senkrechten long.2 (Spalte A: long.4) und von dort auf K, B oder C. Die Eingangs-Muxe der Puffer: `CLK.AA.I` (GCLK, 6 Bits) wählt P9, P11, `col.A.local.3`, `col.A.long.3`, `row.A.long.3` oder in der Grundstellung `row.A.local.3`; `CLK.II.I` (ACLK, 8 Bits) P43, P46, `col.I.local.2`, `col.I.long.2`, `row.I.long.1`, in der Grundstellung `row.I.local.2` oder den Quarzoszillator (ohne Bel, nicht im Graphen). Weil ein Puffer immer treibt, sind die PIPs von ACLK auf die long.2 gerichtet: ACLK ist kein freier Leitungsweg. nextpnr benutzt die Puffer standardmäßig: Ein Takt an P9 oder P11 (GCLK) bzw. P43 oder P46 (ACLK), der nur Speicherelemente taktet, läuft ganz über seinen Puffer, und `pack()` legt Takte ohne Pin an diese Pads. `--vopt noclkbuf` sperrt die Eingänge der Puffer, dann läuft ein Takt wie jedes Signal, an K über die senkrechte long.2 der Spalte (so taktet XACT in `COUNTER.BIT`) | Datenblatt *Longlines*, Bild 8b; Codes aus `MAKEBITS` (siehe [Taktpuffer](#taktpuffer-eingänge-makebits)) |
| Konstanten | Keine Konstanten-Leitung, wie im Original: `pack()` faltet einen konstanten LUT-Eingang in den LUT-Inhalt, lässt Set/Reset = 0 weg und setzt für alles Übrige (konstanter Pad-Ausgang, Set = 1, …) eine LUT mit festem Inhalt ein | – |
| Gehäuse | `--vopt package=PC68` (Standard, 68-Pin-PLCC, alle 58 Pads, Pin = Pad), `PD48` (48-Pin-DIL, 40 Pads; nur -50), `PC44` (44-Pin-PLCC, 34 Pads; -70, -100) oder `PG68` (68-Pin-PGA, Pins A2…L10, 57 Pads; -50, -70, -100). PCF und LOC nennen den Pin des Gehäuses, der Placer nimmt nur bebondete Pads. Die beiden Data Books weichen an zwei Stellen ab: PC44-Pin 20 liegt 1994 auf P30, 1993 auf P31. Hier gilt 1994, denn beim XC2018 ist PC44-Pin 20 wie P30 des XC2064 der Konfigurationspin LDC (die Familie ist im PC44 pinkompatibel). Den PGA-Pin von P65 nennt 1993 B8, 1994 D8 (kein Randpin); hier B8. Für P43 (XTL2 oder I/O) und RESET nennen beide keinen PGA-Pin (übrig sind K10 und L10), P43 fehlt deshalb im PG68 | *Configuration Pin Assignments* (Data Book 1994 S. 2-214, 1993 S. 2-206, XC2018 S. 2-207) und *Component Availability* (1993 S. 2-208, 1994 S. 2-216); `xc2064db/packages.py` |
| IOBs | **58 Pads mit PLCC68-Namen** (Bel `P9` usw.), je Pad-Kachel bis zu zwei. Alle Verbindungen aus `iob.js`, an den Leitungen **beider Kanäle** am Pad (parallel und senkrecht zum Rand): Ausgang zum Pad (Bel-Pin I, im Datenblatt „O“) über einen Multiplexer mit Mux-Code aus 6–9 Quellen (Einzelsegmente, Long Lines, X/Y der Rand-CLB, an P9 GCLK, an P43 ACLK). Tristate T (1 schaltet den Treiber ab) über einen Multiplexer aus 2 Einzelsegmenten und 2 Long Lines des Kanals parallel zum Rand. Eingang vom Pad (Bel-Pin O) über PIP-Bits auf 5–7 Leitungen und fest auf Eingänge der Rand-CLB. Der Modus des Ausgangstreibers ist Konfiguration (Code des T-Multiplexers), kein Pip: an (`XC2000_OUTBUF`), aus (`XC2000_INBUF`) oder Tristate (`XC2000_TOBUF`, `XC2000_IOBUF`, T geroutet). Direktverbindungen: rechts nehmen beide Pads X und Y einer CLB der Spalte H (das erste die daneben, das zweite die darüber); oben treibt das erste Pad A und B, das zweite nimmt X der CLB links; unten treibt das erste Pad C und D, das zweite nimmt X; links treibt das zweite Pad B der CLB darüber, P24 B der CLB HA. Das IOB oben verhält sich damit wie eine CLB darüber, das unten wie eine darunter | `iob.js`; Datenblatt, Abschnitte *I/O Block* und *Direct Interconnect*. Die Kreuzungen ohne PIP-Bit an P9 und P11 (`col.A.io2`) und der Eingang von P43 (`@aclk_in`) sind Quellen der Taktpuffer-Muxe; 6 weitere Kreuzungen mit `col.A.io2` (P13–P23) fehlen, für `MAKEBITS` sind sie nicht programmierbar |
| Gelatchte Eingänge | `XC2000_INFF` (PAD, K → O): das FF zwischen Pad und Eingang, das der Eingangsmultiplexer statt des direkten Wegs wählt (XACT `I:Q`). Steigende Flanke, nach dem Laden 0, kein Set/Reset, keine Taktumkehr. Takt: **je Chipseite eine Taktleitung** außen am Rand (oben `row.A.local.0`, rechts `col.I.local.5`, unten `row.I.local.5`, links `col.A.local.0`), an der der Takteingang jedes IOB der Seite fest hängt (Knoten `IOCLK.T/R/B/L`). Sie speist ein **K-Mux** an einer Ecke mit Code (4 Bits, die die Bitkarte P9, P59, P27 bzw. P24 zuordnet) aus dem Randkanal derselben Seite: oben GCLK, `row.A.local.1-4`, `row.A.long.3`; rechts `col.I.long.2`, `col.I.local.1-4`; unten `row.I.long.1`, `row.I.local.1-4`; links `col.A.local.1-4`, `col.A.long.3`, GCLK. Alle gelatchten Eingänge einer Seite haben also denselben Takt (`isBelLocationValid`, mit PCF ein Fehler in `pack()`). Je eine Quelle rechts und unten (`col.I.io3`, `row.I.io4`) ist eine Stichleitung, deren Signal unbekannt ist, und fehlt | Data Book 1993, *I/O Block* (S. 2-180/2-181, Bild 3: „edge-triggered D flip-flop“, „I/O Blocks along each edge of the die share common clocks“) und *IOB Switching Guidelines* (S. 2-214: Setup/Hold an der steigenden Flanke); `iob.js` (kin, die vier K-Muxe mit Codes); `TEST1.LCA` (P8 `I:Q`, K-Mux oben auf Code 8 = `row.A.local.1`, eine der beiden Kreuzungen, die XACT dort nennt). Nicht am Chip geprüft: Flanke und Codes |
| Timing | Geschwindigkeitsstufen über den Gerätenamen: `XC2064-50`, `-70`, `-100`, `-130` (ohne Zusatz -70; die Zahl ist die Umlaufrate eines FF in MHz). CLB und IOB nach den Tabellen des Data Books, bei -70: T_ILO 10 ns (Eingang bis Ausgang, im Modell 6 ns Funktion = T_QLO plus 4 ns Ausgangstreiber), T_CKO 10 ns (6 ns Clock-to-Q plus Treiber), T_ICK 7 ns (Setup an D also 1 ns), Takt über C 3 ns und über G 4 ns später als über K (aus T_CCO, T_CIO), Pad bis Eingang T_PID 6 ns, Ausgang bis Pad T_OP 9 ns, T bis Pad 15 ns. Interconnect als RC-Kette: jeder Schalter (Switch-Matrix, PIP, Eingangs-Mux) ist ein Widerstand vor der Kapazität der Leitung dahinter, die Kette beginnt an jedem Treiber neu (CLB-Ausgang, Taktpuffer); bei -70 kostet ein Einzelsegment hinter einem Schalter etwa 0,5 ns, eine Long Line 4 ns, der Taktpuffer 4 ns, die anderen Stufen im Verhältnis von T_ILO | Xilinx *Programmable Logic Data Book*, XC2000 *CLB Switching Characteristic Guidelines* und *IOB Switching Guidelines*: -50 (die einzige Stufe im PD48) aus dem von 1993 (S. 2-213, 2-214), -130 aus dem von 1994 (S. 2-221, 2-222), -70 und -100 stehen in beiden gleich. Bei -50: T_ILO 15, T_QLO 8, T_CKO 15, T_ICK 9, T_CCO 19, T_CIO 27, T_PID 8, T_OP 12, T_THZ/T_TON 20 ns. Für das Interconnect nennt das Buch keine Zahlen, nur das RC-Modell (*Interconnect Performance*): R, C und der Taktpuffer sind Schätzungen. Die Repowering-Puffer beenden die RC-Kette im Original, im Modell nicht (eher zu langsam). Speicherelement: `pack()` wählt je Zelle eine Timing-Variante (FF mit steigender bzw. fallender Flanke, Latch transparent bei Takt 1 bzw. 0 mit Setup und Hold an der schließenden Flanke). Set/Reset sind kombinatorische Bögen S/R → Q = T_RLO − T_ILO (-70: 11 ns), so ergibt der Weg über F bzw. G genau T_RLO; direkt von A bzw. D kommt die Pip-Klasse SRDIR = T_RIO − T_RLO + T_QLO dazu (-70: 1 ns, zusammen T_RIO). Beim Latch läuft D → Q = T_ITO − T_ILO (-70: 4 ns), über F also T_ITO. Würde ein solcher Bogen eine kombinatorische Schleife schließen (Q über Logik zurück an D, S oder R), lässt `pack()` ihn weg, sonst bräche das Timing von nextpnr ab. Nicht nachgebildet: T_RS, T_RPW und T_MRQ (RESET-Pin). Gelatchter Eingang: Takt bis Eingang T_LI (-50/-70/-100/-130: 15/11/8/7,5 ns), Setup am Pad T_PL (8/6/4/2 ns), Hold T_LP (0, bei -130 4 ns); die Taktleitung einer Seite zählt wie eine Long Line |

### Regeln in `nextpnr/xc2064.cc`

`isBelLocationValid` prüft je CLB:

1. FG (4 Variablen) bzw. FGM (Mux-Modus) und F/G (3 Variablen) schließen sich aus.
2. Das Speicherelement bekommt seine Daten nur von F bzw. FG derselben CLB.
3. Alle Eingänge (LUT-Pins, Takt, Set, Reset) lassen sich über die Multiplexer des Originals versorgen,
   und A–D führen dabei je höchstens ein Signal. Das ist eine exakte Zuordnungsprüfung (Backtracking).
   Interne Quellen (Q, F, G) und K (von long.2 oder GCLK) belegen keinen der Eingänge.
4. Höchstens zwei Signale verlassen die CLB, denn es gibt nur X und Y. In der CLB bleiben nur die festen
   Wege F → D und Set, G → Reset und Takt sowie Q → Eingang 3. Ohne diese Regel konnte eine CLB mit F, G
   und FF entstehen, deren drei Ausgänge der Router nie unterbringt (gefunden mit `bcd7seg.v`).

`pack()` hält LUT und FF als Cluster zusammen. Liegt der eigene FF-Ausgang Q nicht an Eingang 3 des
LUTs, tauscht `pack()` die Eingänge und permutiert INIT, damit die Q-Rückführung genutzt wird. Ein
unbelegter LUT-Eingang liest im Chip trotzdem eine Leitung (die Grundstellung seines Muxes); `pack()`
macht den LUT-Inhalt daher unabhängig von ihm.

Hat ein Design mehr LUT-Zellen als der Chip CLBs (64), legt `pack()` LUT3 paarweise als F und G in eine
CLB (`pair_lut3`). Sonst verteilt der Placer (HeAP) die LUT3 einzeln über den Chip, und für LUT4 und FGM,
die eine ganze CLB brauchen, bleibt kein Platz mehr („Unable to find legal placement“, gefunden mit
`bcd7seg.v`: 52 LUT3 und 28 LUT4). Ein LUT3/FF-Cluster nimmt eine freie LUT3 als G, sonst bilden zwei
freie LUT3 einen neuen Cluster. Vorrang haben LUTs, die Reset oder Takt des FF liefern oder sein Q lesen
(beides bleibt in der CLB, Q dann an Eingang 3), danach die Zahl gemeinsamer Eingänge; Paare ohne
Gemeinsamkeit nur, solange mehr als 85 % der CLBs gebraucht würden. Jedes Paar prüft dieselbe Regel wie
`isBelLocationValid`.

Je IOB prüft `isBelLocationValid`, dass alle gelatchten Eingänge (`XC2000_INFF`) einer Chipseite am
selben Takt hängen, denn sie teilen sich eine Taktleitung. Liegen sie per PCF schon anders fest, bricht
`pack()` mit einer Meldung ab.

Ein konstantes T ist im Original kein Signal, sondern der Modus des IOB (Code des T-Multiplexers), und
der Routing-Graph hat dafür keine Pips. `pack()` macht deshalb aus `XC2000_TOBUF`/`XC2000_IOBUF` mit
T = 0 einen `XC2000_OUTBUF` (beim `IOBUF` lesen die Nutzer von O dann direkt I) und mit T = 1 einen
`XC2000_INBUF` (Hinweis im Log).

Die Primitive heißen mit dem Familienpräfix `XC2000_` (wie `CC_` bei GateMate), damit sie sich nicht
mit Zellen anderer Bibliotheken verwechseln lassen: `XC2000_LUT3`, `XC2000_LUT4`, `XC2000_DFF` und die
IO-Puffer `XC2000_INBUF`, `XC2000_INFF` (gelatchter Eingang), `XC2000_OUTBUF`, `XC2000_TOBUF`
(Tristate-Ausgang) und `XC2000_IOBUF` (bidirektional, wie `CC_TOBUF`/`CC_IOBUF` bei GateMate). Die Bel-Typen in der Chip-Datenbank bleiben
kurz (`LUT3`, `LUT4`, `DFF`, `IOB`), `getBelBucketForCellType()` ordnet sie zu. Zum Gegenstück in
yosys siehe unten.

Pins stehen in einer **PCF-Datei** wie bei iCE40 (`set_io [-nowarn] <Port> <Pin>`, Busse als
`leds[0]`, Pins als Pin des Gehäuses: P2…P68 im PC68, P1…P48 im PD48), die nextpnr mit
`--vopt pcf=<Datei>` liest. `flow.sh` nimmt `design.pcf` neben `design.v` automatisch, `PCF=…` wählt eine
andere. Ohne Eintrag entscheidet der Placer. Takte legt `pack()` selbst an die Pads der Taktpuffer (außer
mit `--vopt noclkbuf`): das Netz mit den meisten Speicherelementen an GCLK (P9, ist es belegt P11), das
nächste an ACLK (P43, sonst P46, etwa im PG68 ohne P43). Liegt an einem Pad eines Puffers schon ein Takt
per Constraint, bleibt der Puffer diesem; ein Takt, der per Constraint an einem Pad ohne Puffer liegt,
bleibt dort (Hinweis im Log). Takten zwei Netze an P9 und P11 (bzw. P43 und P46) nur Speicherelemente,
bekommt das mit den meisten den Puffer und das andere läuft über das allgemeine Routing (Hinweis im
Log). Alternativ geht weiterhin
`(* LOC="P9" *)` an einem IO-Puffer im Verilog, die PCF-Datei hat Vorrang. `pack()` belegt diese Pads schon beim Packen fest (wie GateMate),
die GUI zeigt sie also direkt nach „Pack“ als belegt. Ein BEL-Attribut setzt es dabei nicht, sonst würde
der Placer die Zellen ein zweites Mal binden wollen.

yosys (`yosys/synth_xc2064.cc`):
- Tristate wie bei GateMate: Nach dem Flatten macht `tribuf -logic` interne Tristate-Netze zu Logik,
  `deminout` macht nur gelesene `inout`-Ports zu Eingängen. `iopadmap` setzt an Ports mit
  Tristate-Treiber `XC2000_TOBUF` bzw. `XC2000_IOBUF` ein, und zwar vor dem LUT-Mapping. Dann geht der
  Inverter (Enable in yosys, T = 1 schaltet ab) noch in einem LUT auf, und bei Low-aktivem Enable
  verschwindet er ganz.
- Zustandsautomaten behalten die Kodierung aus dem RTL (`synth -nofsm`): yosys würde sie oft one-hot
  umkodieren, beim XC2064 mit einem FF je CLB teuer (`ampel.v`: 11 statt 9 FFs), und das Zustandsregister
  hieße nicht mehr wie im RTL, was den formalen Vergleich im Regressionstest bricht. `synth_xc2064 -fsm`
  schaltet die Umkodierung ein.
- `abc -lut 3:4` bewertet einen LUT4 mit den Kosten zweier LUT3.
- `dfflegalize` erlaubt FF und Latch mit beiden Taktpolaritäten und asynchronem Set/Reset.
- Der Pass `xc2064_fgm` (nach dem LUT-Mapping, abschaltbar mit `synth_xc2064 -nofgm`) fasst den LUT vor
  einem Speicherelement mit LUTs davor zusammen, die nur ihn speisen, wenn das Ganze eine Funktion von
  genau 5 Signalen ist, darunter das eigene Q, und die Form `S ? f(a, c, x) : g(a, c, Q)` hat (oder F und
  G vertauscht). Dann wird daraus ein `XC2000_FGM`: S an B, a und c an Eingang 1 und 2 beider Tabellen, x
  bzw. Q an Eingang 3. Mit weniger Signalen reicht ein LUT4, ohne Q bringt FGM nichts. Bisher prüft der
  Pass nur LUTs direkt vor dem D-LUT (eine Ebene)
- Der Pass `xc2064_iobff` (abschaltbar mit `-noiobff`) legt ein FF ins IOB, dessen D direkt an einem
  Eingang hängt, wenn sonst nichts diesen Eingang liest und das FF auf die steigende Flanke ohne Set/Reset
  schaltet: aus `XC2000_INBUF` und `XC2000_DFF` wird ein `XC2000_INFF`. Das spart je Eingang eine CLB.
  Eingänge von `inout`-Ports (`XC2000_IOBUF`) bleiben direkt
- Der Pass `xc2064_ffbuf` gibt jedem FF einen eigenen treibenden LUT (bzw. FGM).
- Die eigenen Zelltypen stehen nicht in yosys' `kernel/constids.inc`. `ID(...)` geht dafür bei
  aktuellem yosys (Twine-IdStrings) nicht, der Pass legt sie mit `design->twines().add(...)` an.

Standard-Router ist `router2`. Er sucht jedes Netz nur in dessen Bounding Box plus einem Rand von
normalerweise 3 Kacheln. Bei knappen Kanälen reicht das nicht immer, dann wechseln sich zwei Netze an
einem Draht ab, und router2 kommt nicht mehr zum Ende (er hat kein Abbruchlimit). `preRoute()` setzt den
Rand deshalb auf die Chipgröße, wenn die Einstellungen `router2/bbMargin/x` und `/y` nicht schon gesetzt
sind. `--router router1` bleibt möglich.

Mit dem geratenen Routing-Graphen vor Stufe 2 (4 Spuren je Kanal, angenommene Matrix-Muster, 6–7 Quellen
je CLB-Eingang) liefen im Regressionstest zwei Platzierungen in den Timeout, eine brauchte 26.500
Iterationen. Mit dem Graphen aus den Daten (5 senkrechte Einzelsegmente, das echte Matrix-Muster, bis zu
10 Quellen je Eingang) routen alle 42 Läufe, der längste braucht 593 Iterationen, der ganze Test 54 s
statt 11,5 min. Mit den IOBs aus `iob.js` (Stufe 3, Pads an beiden Kanälen) braucht der längste Lauf
80 Iterationen, mit dem Timing aus Stufe 4 117. Die Spalte *Routing* des Tests zeigt das. Mit dem
Rundlauf über den Bitstream (Stufe 5) dauert der ganze Test etwa 4 min, mit `shiftreg.v` und `inreg.v`
(Stufen 6 und 7) und den Läufen in PD48, PC44 und PG68 (Stufe 8, zusammen 85 Läufe, der längste mit 97
Iterationen) knapp 4 min, wenn sonst nichts läuft. Seit die Läufe parallel laufen (Stufe 9, 10 Jobs),
braucht der ganze Test mit der Gegenprobe über Shirriffs Decoder knapp 1 min, mit den größeren Designs
aus Stufe 10 (136 Läufe, der längste mit 1238 Iterationen) knapp 3 min, mit den Läufen über die
Taktpuffer aus Stufe 11 (152 Läufe) 2,5–3 min. Mit den Taktpuffern als Standard (Stufe 12, der Takt
der Beispiele läuft über GCLK statt über die long.2 jeder Spalte) braucht der längste Lauf 276
Iterationen, der ganze Test gut 2 min.

## Ablauf

```bash
scripts/build-nextpnr.sh debug              # nach Änderungen an nextpnr/* (inkl. Generator)
arch/xc2064/flow.sh                         # Synthese + Place & Route mit examples/blinky.pcf (5 MHz, FREQ=… ändert es)
SEED=1 arch/xc2064/flow.sh                  # mit festem nextpnr-Seed (ohne SEED: nextpnr-Standard)
arch/xc2064/flow.sh arch/xc2064/examples/latch_sr.v   # anderes Design
arch/xc2064/flow.sh --gui                   # mit nextpnr-GUI: Pack, Place, Route über die Werkzeugleiste
arch/xc2064/test/run.sh                     # Regressionstest (siehe unten)
arch/xc2064/test/bitstreams.sh              # Datenquellen, xc2064unpack, xc2064pack und Shirriffs Decoder mit XACT-Bitstreams prüfen
nextpnr-himbaechel --device XC2064 --json build/flows/xc2064/blinky.pnr.json --gui   # geroutetes Ergebnis ansehen
```

### Bitstream

```bash
arch/xc2064/flow.sh arch/xc2064/examples/blinky.v --vopt out=build/flows/xc2064/blinky.cfg.txt
python3 arch/xc2064/tools/xc2064pack build/flows/xc2064/blinky.cfg.txt -o build/flows/xc2064/blinky.rbt
python3 arch/xc2064/tools/xc2064unpack build/flows/xc2064/blinky.rbt -o blinky.txt     # Rückweg als Text
python3 arch/xc2064/tools/xc2064netlist build/flows/xc2064/blinky.rbt --meta build/flows/xc2064/blinky.cfg.txt -o blinky.bit.v
```

Für den XC2064-50PD48 kommen `--device XC2064-50 --vopt package=PD48` und eine PCF mit den DIL-Pins dazu,
entsprechend `--vopt package=PC44` (Pins P2…P44) bzw. `PG68` (Pins wie B5);
`xc2064pack` übernimmt das Gehäuse aus der Textdatei in den RBT-Kopf (`2064PD48`, `2064PC44`, …). Die RBT-Datei hat
genau den Aufbau von XACT (7 Textzeilen, Kopf, 160 Rahmen, `11111111`, CRLF), für den STM32-Lader aus
[dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026); `-o datei.bit` schreibt
stattdessen die binäre Form.

Ein schon geroutetes `*.pnr.json` lädt nextpnr in der GUI direkt. Auf der Kommandozeile braucht es
`--no-pack`, das Ergebnis ist schon gepackt. Eine andere Geschwindigkeitsstufe wählt der Gerätename,
etwa `--device XC2064-50` für den XC2064-PD48 (ohne Zusatz -70).

| Beispiel | Inhalt | Ergebnis |
|---|---|---|
| `examples/blinky.v` | 16-Bit-Zähler, Pins in `blinky.pcf` (Takt an P9, alles am oberen Rand) | 20 LUT3, 7 LUT4, 16 FF, bei -70 je nach Seed 13,9–14,3 MHz (Standard-Seed 14,0 MHz, Seed 1 mit `flow.sh --seed 1` oder `SEED=1 arch/xc2064/flow.sh` 14,1 MHz), bei -50 9,5 MHz (im PD48 9,4 MHz). Ohne PCF (`PCF=/dev/null`) je nach Seed 13,7–14,4 MHz. Der Takt läuft über GCLK; ohne die Taktpuffer (`--vopt noclkbuf`, über die long.2 jeder Spalte) 14,4 MHz mit PCF. Die Werte verschieben sich mit jeder Änderung an Routing-Graph und Timing. Der kritische Pfad sind die LUT-Ebenen der Zähler-Logik, eine Carry-Kette hatte erst der XC4000 |
| `examples/latch_sr.v` | FF mit fallender Flanke, FF mit asynchronem Set/Reset, Latch, Pins in `latch_sr.pcf` | 3 Speicherelemente mit `CLKINV`, `S`/`R` bzw. `LATCH`. Ohne PCF kommt `clk` an P9 (GCLK) und das Latch-Enable `en` an P43 (ACLK), im PG68 an P46 |
| `examples/tristate.v` | 4-Bit-Bus (`inout`) mit Low-aktivem `oe_n`, Tristate-Ausgang `tout` mit `en_n`, Pins in `tristate.pcf` (alles am oberen Rand) | 4 `XC2000_IOBUF`, 1 `XC2000_TOBUF`, 7 LUT3, 1 LUT4, 8 FF, bei -70 je nach Seed 54–56,5 MHz (-50: 38,8 MHz). T aller Bus-Bits hängt ohne Logik am Pad von `oe_n` und läuft über eine Long Line des oberen Randkanals (die T-Quellen dort: 2 Einzelsegmente und 2 Long Lines). Mit High-aktivem Enable (Inverter in einer CLB, deren Ausgänge die waagerechten Long Lines nicht erreichen, also nur über die Spuren zu den T) war der Bus dort nicht routbar |
| `examples/shiftreg.v` | 8-Bit-Schieberegister mit parallelem Laden (`load`, `din`) und Enable (`en`, `sin`), Pins in `shiftreg.pcf` (Steuerung und `din` oben, `q` rechts) | 8 `XC2000_FGM`, 8 FF in 8 CLBs: jedes Bit ist `load ? din[i] : (en ? q[i-1] : q[i])`, F liest `din[i]` an D, G `en`, `q[i-1]` und das eigene Q, B = `load` wählt. Bei -70 je nach Seed 54–57 MHz (-50: 39 MHz). Mit `synth_xc2064 -nofgm` 9 LUT3 und 7 LUT4 in 16 CLBs, 34,8 MHz (Standard-Seed mit PCF) |
| `examples/inreg.v` | Eingänge über das FF im IOB: `d` in die IOBs, eine zweite Stufe in den CLBs und ein Flankendetektor (`rise`); Pins in `inreg.pcf` (`d[1:0]` oben, `d[3:2]` links, also zwei K-Muxe am selben Takt) | 4 `XC2000_INFF`, 4 FF, 8 LUT3 in 8 CLBs. Der Takt kommt oben und links über GCLK in die K-Muxe, ohne die Taktpuffer (`--vopt noclkbuf`) oben über `row.A.long.3`, links über `col.A.long.3`. Bei -70 je nach Seed 53–55 MHz. Mit `synth_xc2064 -noiobff` 8 FF und 12 LUT3 in 10 CLBs, 58,8 MHz (Standard-Seed mit PCF): T_LI (11 ns) ist länger als Clock-to-Out einer CLB, und der Takt der IOBs läuft über K-Mux und Taktleitung der Seite |
| `examples/uart_tx.v` | UART-Sender 8N1 (`start`, `data`, `tx`, `busy`; 434 Takte je Bit), Pins in `uart_tx.pcf` (Eingänge oben, `tx` und `busy` rechts) | 23 FF, 7 `XC2000_FGM`, 23 LUT3, 22 LUT4 in 46 CLBs. Bei -70 je nach Seed 15,5–16,2 MHz, router2 braucht bis zu 142 Iterationen. Das Schieberegister mit Laden nutzt den Mux-Modus FGM |
| `examples/ampel.v` | Zustandsautomat: Fußgängerampel mit Taster, gemeinsamem Phasenzähler und gespeicherter Anforderung, Pins in `ampel.pcf` | 9 FF (Zustand binär wie im RTL, siehe yosys oben), 17 LUT3, 6 LUT4 in 19 CLBs, je nach Seed 18,9–19,8 MHz |
| `examples/bcd7seg.v` | Vierstelliger BCD-Zähler mit Vorteiler und gemultiplexter 7-Segment-Anzeige (registriert), Pins in `bcd7seg.pcf` (Segmente rechts, Stellen unten); das große Design | 33 FF, 45 LUT3, 23 LUT4 in 54 der 64 CLBs (84 %), `pack()` legt 14 LUT3 paarweise in CLBs. Je nach Seed 13,4–14,0 MHz, alle Läufe in höchstens 4 s. Mit `PRESCALE=10` 58 CLBs (91 %): alle Läufe bestehen in höchstens 8 s (ohne die Taktpuffer braucht einer 105 s, bis Stufe 11 einer 3 min); mit `PRESCALE=50` 61 CLBs (95 %): 1 von 17 Läufen (PD48) läuft nach 300 s mit noch 1 überbelegten Draht in den Timeout, einer braucht 226 s (echter Stau im Debug-Build; bis Stufe 11, mit dem Takt über die long.2, liefen 4 von 17 in den Timeout) |

In VS Code laufen die allgemeinen Tasks *Arch: Flow ausführen* und *Arch: Flow mit nextpnr-GUI* sowie
die Debug-Konfigurationen für Architekturen (Run and Debug). Als Namen jeweils `xc2064` eingeben.

### Regressionstest

`test/run.sh [design.v …]` synthetisiert jedes Beispiel (ohne Argument alle `examples/*.v`), routet es
mit dem nextpnr-Standard-Seed und den Seeds 1–6, mit und ohne PCF, dazu ohne PCF je einmal in den
Gehäusen PD48, PC44 und PG68 (Spalte PCF, `PACKAGES=…` ändert die Liste) und mit und ohne PCF je einmal
ohne die Taktpuffer (`--vopt noclkbuf`, Spalte Seed `noclkbuf`), und prüft jeden Lauf. Die Spalte
Bitstream verlangt zusätzlich, dass die Konfiguration einen Taktpuffer benutzt (jedes Beispiel hat einen
Takt vom Pad), bei `noclkbuf` keinen. Zeilen
`// erwartet: <Zelltyp> <Anzahl>` im Design prüfen schon die Synthese (`shiftreg.v` verlangt 8
`XC2000_FGM`, fällt der Pass aus, schlägt der Test fehl). Die Läufe laufen parallel, höchstens
`TEST_JOBS` gleichzeitig (Standard `JOBS`, nie mehr als 10); die Zeilen erscheinen trotzdem in fester
Reihenfolge:

| Spalte | Prüfung |
|---|---|
| PnR | nextpnr endet ohne Fehler innerhalb von `TIMEOUT` Sekunden (Standard 300, router2 hat kein Abbruchlimit). Verfehltes Timing allein ist kein Fehler (`--timing-allow-fail`) |
| Netz | Die Netzliste nach dem Routing (`*.pnr.json`, also nach `pack()` mit Eingangstausch, INIT-Permutation und Konstanten) ist formal äquivalent zum RTL |
| Pips | `test/extract_netlist.py` gewinnt die Netzliste allein aus den belegten Bels und den benutzten Pips zurück, also aus dem, was ein Bitstream festhält. Jeder Eingang muss am Treiber hängen, den die Netzliste von nextpnr vorsieht, keiner darf zwei haben, und kein benutzter Pip darf verwaist sein. Die so gewonnene Netzliste muss ebenfalls äquivalent zum RTL sein. Das deckt Platzierung und Routing mit ab |
| Bitstream | Rundlauf über den echten Bitstream: nextpnr schreibt die Konfiguration als Text (`--vopt out=`), `xc2064pack` macht daraus eine RBT-Datei, `xc2064unpack` und noch einmal `xc2064pack` geben sie bitgenau wieder, und `xc2064netlist` gewinnt allein aus der RBT-Datei (Namen von Ports und Registern aus der Textdatei) eine Netzliste zurück, die formal äquivalent zum RTL sein muss. Ein verfälschtes LUT-Bit fällt dabei auf |
| Shirriff | Unabhängige Gegenprobe: Shirriffs Decoder (`tools/xc2064shirriff`) liest die RBT-Datei mit seinem eigenen Leser und muss sie so dekodieren wie das Paket (siehe unten). `-` ohne das Python-Paket `quickjs` |
| Fmax | Kleinste Frequenz aller Takte. Mit `FMIN=…` (MHz) ist ein Wert darunter ein Fehler |
| Routing | Iterationen und Laufzeit von router2, nur zur Information |

Der Vergleich läuft in yosys. Das RTL liest er mit `proc -norom`, damit große `case`-Anweisungen
(7-Segment-Decoder) Logik bleiben, denn ein ROM kann `equiv` nicht rechnen. `equiv_make` paart die
gleichnamigen Signale (Ports und Register),
`clk2fflogic` bildet die Takte mit ihrer Flanke nach (`CLKINV` zählt also mit), und `equiv_induct`
beweist die Gleichheit für alle Eingangsfolgen. Als Modelle dienen `yosys/cells_sim.v` und für die
Konstanten-Zellen, die nextpnr bis Stufe 3 anlegte, `test/pnr_cells.v` (seit Stufe 4 sind Konstanten
gewöhnliche LUTs). Ein verändertes INIT-Bit, vertauschte
LUT-Eingänge, ein umgedrehtes `CLKINV`, ein FF statt Latch, ein gelöster Pip oder ein LUT-Eingang an
der falschen Quelle fallen jeweils auf.

Die Rundläufe prüfen das Paket mit sich selbst: Ein Fehler, der beim Schreiben und Lesen gleich ist
(etwa eine falsche Bitreihenfolge der LUTs), fiele dort nicht auf. Deshalb läuft zusätzlich Shirriffs
Decoder aus `shirriff-xc2064/html` (`draw.js`, `karnaugh.js`, `parse.js`, `iob.js`, `clb.js`) ohne Browser in
QuickJS (Python-Paket `quickjs`, steht in `.devcontainer/requirements.txt`; `xc2064db/shirriff.py` stellt
`window`, `$`, `alert` und `assert` bereit). Verglichen werden je Bitstream:

- das Innere aller 64 CLBs: Basis (F, FG, FGM), Eingänge von F und G, beide Wahrheitstabellen, X, Y, FF
  oder Latch, Set, Reset und Takt. Das ist der unabhängige Teil, denn Shirriff liest diese Bits aus der
  Bit-Tabelle in Chip-Lage mit eigener Bitreihenfolge, das Paket über die Namen der Bitkarte;
- die gewählte Quelle der 320 CLB-Eingänge (G-Lage der Kreuzung) und der O-, T- und K-Muxe der IOBs
  (Index in der Liste von `iob.js`, bei Leitungen auch die G-Lage), dazu gelatchte Eingänge. Diese Tabellen
  hat das Paket aus `clb.js` und `iob.js` übernommen, der Vergleich prüft die Übernahme;
- Pips, Switch-Verbindungen und Puffer.

Bekannte Abweichungen rechnet der Vergleich heraus: Beim Takt unterscheidet Shirriff K und G anders als
XACT (`TEST1.LCA`), verglichen wird nur aus, über C (mit Umkehrung) oder über K bzw. G; in Zeile I
vertauscht er die Matrizen 8.1 und 8.2; bei Basis F und FGM heißt der gemeinsame Ausgang bei ihm F bzw. M.
Alle zehn XACT-Bitstreams (`test/bitstreams.sh`) und alle Bitstreams des Regressionstests dekodiert er
wie das Paket. Dass der Vergleich etwas findet, zeigen zwei Gegenproben: Shirriffs Dekodierung von
`TEST1.RBT` gegen die eigene von `AND_OR.BIT` ergibt 95 Abweichungen, und zwei vertauschte Codes in der
Tabelle eines CLB-Eingangs fallen sofort auf.

```bash
python3 arch/xc2064/tools/xc2064shirriff build/flows/xc2064/test/inreg/pcf-mit-seed-default.rbt
```

Den hochohmigen Zustand kennt der Vergleich nicht. `test/tristate_split.py` bereitet beide Netzlisten
deshalb auf: Jeder Tristate-Treiber wird ein Multiplexer mit fester 0 bzw. 1 statt Z, und der Vergleich
läuft für beide Werte. Treibt eine Netzliste, wo die andere hochohmig ist, fällt das in einem der beiden
Läufe auf. Jeder `inout`-Port wird ein Ausgang, und was ihn liest, liest stattdessen einen neuen Eingang
`<Port>$ext`, also den Wert, den die Außenwelt anlegt. So ist auch der Lesepfad über O geprüft. Ein T am
falschen Netz, vertauschte I oder O zweier Bus-Bits, vertauschtes T und I oder ein Tristate-Ausgang ohne
T fallen jeweils auf.

Umgebungsvariablen: `SEEDS="1 2 3"` (zusätzlich zum Standard-Seed, leer nur dieser), `FREQ`, `FMIN`,
`TIMEOUT`, `YOSYS`, `NEXTPNR`. Logs, Netzlisten und die Äquivalenz-Logs je Lauf liegen unter
`build/flows/xc2064/test/<design>/`. Das Skript endet mit Fehler, wenn ein Lauf fehlschlägt.

### GUI

Die Grafik ist ein Schaltplan des ganzen Chips mit **allen Leitungen, Bels und Pips**. nextpnr blendet
unbenutzte Pips sonst aus, `xc2064.cc` zeichnet sie gedämpft. Nach dem Routing sind die benutzten
hervorgehoben, so dass sich jeder Pfad vom Pad über Kanäle, Switch-Matrizen und Eingangsmultiplexer bis
in die LUTs und das Flipflop verfolgen lässt. Mit der Maus über einem Pip zeigt die GUI seinen Namen.

Die Ausrichtung folgt Datenblatt und Die-Fotos: X0Y0 oben links. In den Kacheln X1Y1…X9Y9 sitzen oben
links die Switch-Matrizen 8.1 und 8.2, rechts davon der Kanal oberhalb der CLB, darunter der Kanal links
der CLB. Die Linien darin der Graph aus den Daten:

- **Lage:** Die Leitungen liegen in der Reihenfolge und mit den Abständen aus Shirriffs `draw.js`, am Rand
  mit den zusätzlichen Long Lines.
- **Switch-Matrizen:** Ein Rahmen um die Pins. Jede Verbindung des Musters ist eine Linie von Pin zu Pin,
  benutzte leuchten auf.
- **Einzelsegmente** enden an den Rahmen der Matrizen.
- **Fünfte senkrechte Leitung:** Ihr Stück beginnt am Kästchen des Verbindungspunkts oben im Kanal, läuft
  ein Stück auf der Spur von local.6 und knickt dann auf die Spur von local.5. Das Stück der Zeile darüber
  läuft daneben noch bis in den Kanal hinein.
- **Long Lines und GCLK** laufen über die ganze Höhe bzw. Breite. GCLK kommt oben als `CLK.AA.O` vom Pad
  P9, ACLK unten waagerecht vom Pad P43. Die Eingänge der Taktpuffer aus Leitungen sind Kästchen in den
  Ecken: in AA, wo `row.A.local.3`/`row.A.long.3` die Spalte `col.A.clk` und `col.A.local.3`/`col.A.long.3`
  `CLK.AA.O` kreuzen (dafür reicht `CLK.AA.O` in AA bis local.3), in II an `row.I.clk` und an einem Stück
  ACLK am rechten Ende hinauf bis `row.I.long.1`.
- **Repowering-Puffer** sind zwei Dreiecke Spitze an Spitze auf den Einzelsegmenten an den
  Sektionsgrenzen (vor den Kanälen der Zeilen und Spalten D und G). Sie gehören zum Segment und leuchten
  mit ihm auf.
- **PIP-Kästchen** sitzen an jeder Kreuzung, die ein PIP-Bit hat.

Die IOBs sind wie im Datenblatt gezeichnet: außen das Pad, im Rahmen der Ausgangstreiber (Dreieck zum
Pad) mit seinem Multiplexer und dem kleineren Multiplexer für das Tristate, daneben der Eingangstreiber
(Dreieck nach innen). Ausgang, Tristate und Eingang laufen als drei Leitungen quer über den Kanal
parallel zum Rand. Wie bei Shirriff knicken Ausgang und Eingang dahinter in eine Stichleitung parallel
zum Rand ab, die die Leitungen des Kanals senkrecht zum Rand kreuzt; die Tiefe der Stichleitungen ist so
gewählt, dass sich die Pins eines IOB nicht kreuzen. Welche Kreuzungen ein Kästchen bekommen, liest
`xc2064.cc` aus den Pips der Chipdb, die Zeichnung der IOBs braucht also keine eigene Tabelle.
Direktverbindungen: Am rechten Rand laufen X und Y der CLB links durch den Randkanal in den
Ausgangsmultiplexer des ersten IOB; zum zweiten IOB der Kachel darunter knicken sie vor dem Randkanal
nach unten ab. Oben und unten läuft X senkrecht in den Ausgangsmultiplexer des zweiten IOB (dafür ist es
gespiegelt gezeichnet). Der Eingang vom Pad läuft auf seiner Stichleitung oben zu A (Abzweig auf der Spur
von col.x zu B), unten zu D (Abzweig zu C), links zu B der Rand-CLB. An P9 und P43 kreuzt der Eingang die
Taktleitung (`CLK.AA.O` bzw. `row.I.clk`), das Kästchen dort ist der Eingang des Taktpuffers; der
Ausgangsmultiplexer hat an derselben Leitung GCLK bzw. ACLK als Quelle. P11 erreicht GCLK an `col.A.clk`,
P46 ACLK über seine Stichleitung hinab bis `row.I.clk`.

Der Eingang folgt Bild 3 des Datenblatts: Hinter dem Eingangstreiber zweigt er ab, links direkt, rechts
über das FF (Takt mit Dreieck), beide in den Eingangsmultiplexer, dessen Ausgang die Leitung über den
Kanal ist. Ist das IOB belegt, zeigt der Multiplexer den gewählten Weg (`XC2000_INFF`: über das FF). Der
Takt K kommt außen neben dem IOB von der Taktleitung seiner Seite, die ganz außen am Chiprand läuft. Ihr
K-Mux liegt an einer Ecke als Stichleitung auf Shirriffs Spuren: oben `col.I.local.0` links der Spalte I
hinab über die Leitungen der Zeile A, rechts `row.A.local.5` unter dem Kanal der Zeile A, unten
`col.A.local.5` hinauf über die Leitungen der Zeile I, links `row.I.local.0` unter diesem Kanal. Jede
Quelle bekommt dort ein Kästchen.

Eine CLB (grauer Rahmen) folgt dem Blockschaltbild im Datenblatt, von links nach rechts:

| Spalte | Inhalt |
|---|---|
| Eingänge | A, B, C, D als Zeilen von links. A kommt vom Kanal oben, D vom Kanal unten, B und C vom Kanal links |
| Kombinatorische Logik | Schienen Q, D, C, B, A, die Multiplexer der LUT-Eingänge, LUT F, LUT G und FG als Rahmen um beide mit dem F/G-Multiplexer (B wählt); FGM ist derselbe Multiplexer ohne Rahmen |
| Verteiler | F, FG, G mit den Multiplexern für Set (oben), Daten, Takt und Reset (unten) |
| Speicherelement | D und Takt (Dreieck) links, S oben, R unten, Q rechts |
| Ausgänge | Schienen F, FG, G, Q mit den Multiplexern X und Y, beide rechts hinaus durch den Kanal (PIP-Kästchen an ihren Spuren und Long Lines) |

Wie im Datenblatt läuft A über die Logik zum Set-Multiplexer. C, das Taktsignal K (von long.2 oder
GCLK) und D laufen unter der Logik zu Takt und Reset. F, FG und G laufen über dem Speicherelement zu den Ausgängen,
Q läuft unten herum zurück zu den LUTs. Die Direktleitungen von X laufen am rechten Rand hinauf und
hinab zu den Pins der CLB darüber bzw. darunter, Y läuft durch den Kanal weiter in die B-Zeile der CLB
rechts. Keine Leitung läuft durch ein Bauteil. Im Routing zeichnet jedes Wire seine ganze Leitung bis zu
den Kreuzungen, an denen es geschaltet werden kann, auch die Direktleitungen und die Anschlüsse der
Pads. Der Pip ist dort nur das Kästchen, wie Metall und Schalter im Chip. Markiert man ein Wire,
leuchtet also die ganze Leitung. In der CLB sind Pips ein Abgriff mit Punkt an der Schiene. Ein
benutzter Pip zeigt zusätzlich seinen Weg durch den Multiplexer. Im FG-Modus leuchten die Multiplexer
von F und G, der Rahmen und der F/G-Multiplexer. Im Mux-Modus FGM leuchten F, G und der F/G-Multiplexer
ohne den Rahmen (zwei Funktionen), und an F und G jeweils nur die Eingangs-Multiplexer, die ihre
Tabelle braucht.

Weil nextpnr selbst mit y nach oben zeichnet, spiegelt `xc2064.cc` die Grafik. Weil nextpnr `drawPip`
den kanonischen Draht eines Knotens übergibt (der in einer Nachbarkachel liegen kann), sucht
`local_gfx_id()` den Draht in der Kachel des Pips.

Ein Bild des ganzen Chips ohne GUI liefert ein `--post-route`-Skript mit `ctx.writeSVG("chip.svg", "scale=300")`.
Das SVG zeichnet in fester Reihenfolge, nicht nach Zustand. Deshalb kann dort eine gedämpfte Linie eine
benutzte an derselben Stelle überdecken (FG nutzt die Multiplexer von F und G). Die GUI zeichnet
Benutztes immer obenauf.

## Datenquellen und Bitstream-Werkzeuge

Der Weg zu einem echten Bitstream baut auf zwei Submodules auf. Im Submodule selbst ändert nichts, beide
werden nur gelesen.

| Submodule | Commit | genutzt |
|---|---|---|
| `shirriff-xc2064` ([shirriff/xc2064](https://github.com/shirriff/xc2064)) | `4d35c218` (25.05.2021) | `html/XC2064-def.txt` (Name jedes der 11.360 Bits), `html/draw.js` (Leitungsnamen und ihre Lage), `html/clb.js` (CLB-Eingangs-Muxe), `html/iob.js` (IOBs), `obsolete/test/TEST1.RBT` mit `TEST1.LCA` |
| `openxc2064` ([rates37/openxc2064](https://github.com/rates37/openxc2064), MIT) | `db348a02` (03.10.2026) | `bitstream/XACT_comparisons/*.BIT` und `hardware/bitstreams/AND_OR.BIT` (mit XACT erzeugt), `possible_connections` in `bitstream/generate_bitstream.py` als Gegenprobe |

XACT dient nur als Blackbox: MAKEBITS (LCA → Bitstream) und XDELAY laufen ohne Dongle in einer DOSBox
außerhalb des Repos und liefern Gegenproben, etwa die Codes der Taktpuffer-Eingänge. Die Gerätedaten von
XACT (.DEV, .DIE, .BSD, .SPD) werden nicht dekodiert, XACT-Dateien liegen nicht im Repo.

**Abgleich der beiden Quellen** (`python3 -m xc2064db`, siehe unten). Die Herkunft der Daten von
openxc2064 ist dort nicht dokumentiert. Der Abgleich zeigt, dass sie zum großen Teil auf Shirriff aufbauen:

| openxc2064 | Ergebnis |
|---|---|
| `pin_planning/XC2064-def.txt` | Kopie von Shirriffs Datei, also keine unabhängige Bestätigung |
| `bitstream/XC2064-spreadsheet.csv` | dieselbe Bitkarte als Tabelle 71 × 160 (`spreadsheet_maker.py`) |
| `possible_connections` | stimmt mit dem Muster der Switch-Matrizen aus Shirriffs Magic-Bits überein (Pins 0–7 dort = 1–8 bei Shirriff) |
| `src/openxc2064/device/data/xc2064_8x8.json` | Schaltplan des Simulators mit Bildschirmkoordinaten, ohne Bezug zu Bits oder Shirriffs Namen; nicht verwendet |
| XACT-Bitstreams | unabhängig: Mit Xilinx' Software erzeugt. Alle passen zu Shirriffs Bitkarte (kein programmiertes Bit an einer unbenutzten Stelle, jeder CLB-Mux-Code in `clb.js` bekannt) |
| `hardware/bitstreams/LUT_TEST.BIT` | anderes Format (5010 Bytes, anderer Kopf), noch nicht gelesen; COUNTER, LUT2 und PIN_FIND dort gleichen denen unter `XACT_comparisons` |

Abweichungen zwischen den Quellen gibt es bisher keine. Zu Shirriffs Datei: Sie endet bei Bit 11.357, die
Bits 11.358 und 11.359 gelten wie in seinem Viewer als unbenutzt.

**`xc2064db`** (Python-Paket in `arch/xc2064`) liest die Quellen. Es ist die gemeinsame Grundlage für den
Generator der Chipdb (Namen und Verbindungen) und die Bitstream-Werkzeuge (Bitkarte):

| Modul | Inhalt |
|---|---|
| `bitmap` | Art und Felder jedes Bits aus `XC2064-def.txt` |
| `lines` | Leitungsnamen (`col.B.local.1`, `row.C.long.1` …) und ihre G-Koordinaten. Die Ränder liest es als Text aus `draw.js`, die Spalten und Zeilen B–H rechnet es wie dort `initNames()` aus. Ein PIP-Eintrag wie `170G23` ist die Kreuzung zweier Leitungen |
| `switches` | 154 Switch-Matrizen (2 je Kreuzung, keine an den Ecken), Pins 1–8, Verbindungen aus den Magic-Bits |
| `clbmux` | CLB-Eingänge A–D und K: Quellen und Mux-Codes, wie `generateClbPips()` in `clb.js` |
| `bitstream` | `.BIT` und `.RBT` lesen und schreiben |
| `iobmux` | IOBs aus `iob.js`: Quellen und Codes der Ausgangs- und T-Multiplexer, Eingangs-Pips, die vier K-Muxe der gelatchten Eingänge (`kmuxes`), die Eingangs-Muxe der Taktpuffer (`clkmuxes`, Codes aus MAKEBITS) |
| `blocks` | Konfiguration der CLBs (LUTs, Eingangsauswahl, FF/Latch, Takt, Set/Reset, X/Y), der IOBs (Eingang direkt/gelatcht) und der Optionen: Bits ↔ Felder, Grundzustand von XACT |
| `config` | Textformat der Konfiguration: Bits → Text (`decode`), Text → Bits (`encode`) |
| `netlist` | Netzliste aus einem Bitstream (Rückweg für den formalen Vergleich), Funktionsgeneratoren als `XC2000_LUT3`, `XC2000_LUT4` (BASE F) bzw. `XC2000_FGM` (BASE FGM) |
| `packages` | Gehäuse PC68, PD48, PC44 und PG68: Pin → Pad |
| `graph` | Routing-Graph: Segmente aus den Trennstellen an den Matrizen und dem Modell der fünften Leitung, Verbindungen aus PIP-, Magic- und Mux-Bits. Der Generator `nextpnr/xc2064_arch_gen.py` baut daraus die Kacheln, `xc2064unpack` prüft daran die Bitstreams |
| `lca` | `TEST1.LCA` von XACT lesen und gegen Dekodierung und Graph prüfen; eine Konfiguration als LCA für MAKEBITS schreiben (`write`, `tools/xc2064lca`) |
| `shirriff` | Shirriffs JavaScript-Decoder in QuickJS laden, eine RBT-Datei damit dekodieren und mit der eigenen Dekodierung vergleichen (`tools/xc2064shirriff`) |

Was die Daten über das Original sagen:
- **Switch-Matrizen:** Die 98 inneren haben dasselbe Muster mit 20 Verbindungen, jeder Pin mit 5 der 7
  anderen. Die 56 am Rand haben dasselbe Muster ohne die Pins der fehlenden Seite.
- **CLB-Eingänge:** A hat 6–7 Quellen, B 10, C 8, D 6–7 und K 2.
- **IOBs:** Ausgang zum Pad aus 6–9 Quellen, T aus 4 (2 Einzelsegmente und 2 Long Lines des Kanals
  parallel zum Rand), Eingang auf 5–7 Leitungen. Die Leitungen eines Pins an den Kreuzungen
  (`io1`–`io6`, `x`, `clbl`/`clbr`/`clbw`, die Randleitungen local.0 und local.5) sind Teil des IOB und
  keine eigenen Routing-Leitungen. Der Code des T-Multiplexers trägt auch den Modus: Tristate (eine
  Quelle gewählt), Treiber immer an oder immer aus. Die vier K-Muxe der gelatchten Eingänge (je 4 Bits,
  6 Quellen) wählen auch ohne programmiertes Bit eine Quelle (Code 15, wie die O-Muxe); XACT lässt sie
  dort, außer in `TEST1.RBT` am oberen (Code 8, P8 ist gelatcht).
- **Repowering-Puffer:** Die 158 Bidi-Bits, die auch Shirriff nicht dekodiert, tragen als Namen eine
  G-Lage, und die liegt immer auf genau einem Einzelsegment: 86 senkrecht (alle local.1–5 jeder Spalte
  bei G 109 und 52, also kurz vor den Kanälen der Zeilen D und G), 72 waagerecht (bei G 65 und 125, vor
  den Spalten D und G). Das sind die bidirektionalen Puffer an den Grenzen der 9 Sektionen aus dem
  Datenblatt. Ihre Richtung zeigen die XACT-Bitstreams: Bei jedem der 18 Puffer, über die ein Netz von
  seinem Treiber zu einer Senke läuft, ist das Bit 0, wenn das Signal nach unten bzw. rechts läuft, und
  1, wenn es nach oben bzw. links läuft. Puffer auf unbenutzten Segmenten setzt XACT mal so, mal so.
- **CLB-Konfiguration:** 37 Bits je CLB, Bedeutung wie in Shirriffs `clb.js` mit einer Ausnahme beim
  Takt: Das Bit „CLB AB“ wählt C; sonst gilt K, wenn der K-Mux eine Quelle hat, und G, wenn nicht, wobei
  G gegenüber K invertiert ankommt, und ein Latch kehrt „CLK Invert“ um. Shirriff verwechselt hier K und
  G:NOT; `TEST1.LCA` (CLK:K, C, C:NOT, G, G:NOT, Latches) zeigt es eindeutig. LUT-Tabelle: Bit i ist der
  Ausgang für Eingang 1 = i & 1 usw., bei BASE F wählt B (B = 1: Tabelle F).
- **Grundzustand:** XACT setzt für eine unbenutzte CLB genau `BASE FG`, `Select Latch/FF` und
  `Set-Enable`, für ein unbenutztes IOB `I PAD/Latched` und den T-Code „aus“; die 8 Optionen „Other“ sind
  in allen zehn Bitstreams gleich (DONE-Pull-up, Readback, `UNknown 2` gesetzt). `xc2064pack` füllt alles,
  was der Text nicht festlegt, damit.
- **Abdeckung:** Das Paket dekodiert alle 8596 benutzten Bits: Pips, Switch-Matrizen, die Muxe von CLB,
  IOB und Taktpuffern, die Richtung der Puffer, die Konfiguration der CLBs und IOBs und die Optionen. Die
  14 Bits der Taktpuffer-Eingänge `CLK.AA.I` und `CLK.II.I` benutzt kein Bitstream, ihre Codes stammen aus
  MAKEBITS (siehe [Taktpuffer](#taktpuffer-eingänge-makebits)).
- **Routing-Graph:** Er enthält alle 2520 Magic-Bits und alle 1656 PIP-Bits: 798 PIPs zwischen
  allgemeinen Leitungen, 8 gerichtete von ACLK auf die senkrechten long.2 (Spalte A: long.4), 448
  Ausgangs-PIPs von X und Y, 353 Eingangs-PIPs der IOBs und 49 Verbindungspunkte der fünften Leitung. Dazu
  die 2064 Mux-Quellen der CLB-Eingänge und 642 der IOB-Multiplexer (410 Ausgang, 232 T), 22 Quellen der
  K-Muxe mit den 58 festen Takteingängen der IOBs und 12 Quellen der Taktpuffer-Muxe. Nicht im Graphen
  sind 8 Einträge aus `iob.js` und der Oszillator: 6 Kreuzungen mit `col.A.io2` an den zweiten Pads links
  (P13–P23), für die die Bitkarte kein PIP-Bit hat und die auch MAKEBITS nicht programmieren kann (die an
  P9 und P11 sind Eingänge des GCLK-Puffers, `@aclk_in` an P43 der des ACLK-Puffers), und je eine Quelle der
  K-Muxe rechts und unten (`col.I.io3`, `row.I.io4`, Stichleitungen unbekannter Herkunft).
- **Gegenprobe mit XACT:** Alle 210 Routing-Elemente, die XACT in `TEST1.LCA` nennt, stehen in der
  Dekodierung von `TEST1.RBT`. 2 davon sind Kreuzungen am K-Mux oben ohne eigenes Bit: XACT nennt
  `row.A.local.1` und `row.A.local.2`, dekodiert ist Code 8 = `row.A.local.1` (nicht geprüft). 29 sind T-Eingänge
  von Pads, deren Treiber laut T-Code immer an bzw. aus ist (XACT routet T trotzdem, der Multiplexer
  wählt es nicht). Der Graph verbindet die CLB- und IOB-Pins der Netze BC, bc2, BD, bd2, K, p1, P3, P9 und
  q1 genau wie XACT und hält alle Netze getrennt. CB und DB hat XACT selbst nicht geroutet.
  `xc2064unpack` findet alle 127 programmierten Pips und Switch-Verbindungen von `TEST1.RBT` im Graphen.
  Base, Config und Equate aller 42 Blöcke (38 CLBs, 4 IOBs) stimmen mit der Dekodierung überein. Die
  Matrizen der Zeile I benennt das Paket wie XACT (Shirriffs Switch-Klasse vertauscht dort 8.1 und 8.2).
- **Rundlauf:** Alle zehn XACT-Bitstreams ergeben über `xc2064unpack` und `xc2064pack` wieder bitgenau
  sich selbst (`test/bitstreams.sh`).

**Bitstream-Format** (`.BIT` und `.RBT` von XACT): Auf einen 40-Bit-Kopf folgen 160 Rahmen aus Startbit
`0`, 71 Datenbits und `111`. Bit i der Bitkarte steht in Rahmen i // 71 an Stelle i % 71. Ein
programmiertes Bit ist 0. Die RBT-Datei hat davor 7 Textzeilen, etwa `Xilinx LCA TEST1.LCA 2064LPC68`
und `Produced by XACT version 5.1.0`. Sie schreibt den Kopf und jeden Rahmen als eine Zeile, am Ende
steht `11111111`. MAKEBITS 5.2.0 schreibt einen anderen Längenzähler in den Kopf (12049 statt 12045) und 16
Einsen ans Ende; das Lesen nimmt beides mit einem Hinweis an.

**Textformat** (zwischen nextpnr und `xc2064pack`, Rückweg `xc2064unpack`), eine Zeile je Eintrag:

```
device XC2064
package PD48                               # Gehäuse für den RBT-Kopf (PC68 oder PD48)
clb AB BASE:FG F:A:B:C G:A:C:Q LUTF:96 LUTG:E8 X:F Y:G Q:FF SET:A RES:D CLK:K:NOT
iob P8 I:Q                                 # Eingang des IOB direkt (PAD) oder gelatcht (Q, FF im IOB)
mux AB.A row.A.local.1                     # CLB-Eingang und gewählte Quellleitung (oder none)
mux P59.O AH.X                             # Ausgangs-Mux eines IOB: Leitung, X/Y einer CLB, GCLK oder ACLK
mux P59.T col.I.long.2                     # T-Mux eines IOB: Quelle (Tristate), on (Treiber an) oder off
mux P9.K row.A.long.3                      # K-Mux: Takt der gelatchten Eingänge oben (P59 rechts, P27 unten, P24 links)
mux CLK.AA.I P9                            # Eingang des Taktpuffers GCLK (CLK.II.I: ACLK): Leitung, Pad oder OSC
pip col.B.local.5:row.B.local.3            # PIP: Kreuzung zweier Leitungen
switch AB.8.1 3-8                          # Verbindung zweier Pins einer Switch-Matrix
bidi 125G6 right                           # Repowering-Puffer: down/right (Bit 0), sonst up/left
bidi auto                                  # Richtung aller Puffer aus dem Routing (xc2064pack)
other DONE pin Pullup/No Pullup 1          # Optionen
bit <Name>                                 # sonst programmiertes Bit mit Namen (kommt nicht mehr vor)
port P9 clk input                          # (nextpnr) Port am Pad, für den Rückweg zur Netzliste
reg AB ctr[0]                              # (nextpnr) Name des Registers einer CLB, ebenso
reg P8 s1[0]                               # (nextpnr) ... bzw. eines gelatchten Eingangs
```

Die CLB-Felder folgen XACTs `Config` (mit BASE und den Wahrheitstabellen dazu; F und G nennen die
gewählten Eingänge, nicht nur die benutzten). `xc2064unpack` schreibt jede CLB, jedes IOB, jeden Mux und
alle Optionen, dazu jedes programmierte Bit; die Datei ist verlustfrei. nextpnr schreibt nur das Benutzte,
`xc2064pack` ergänzt den Grundzustand von XACT und leitet die Richtung der Puffer ab. Die Zeilen für das
Routing trägt jeder Pip der Chipdb als Zusatzdaten (aus `xc2064db.graph.cfg`).

```bash
python3 arch/xc2064/tools/xc2064unpack TEST1.RBT -o TEST1.txt   # Bitstream -> Text (bricht bei unbekannten Bits ab)
python3 arch/xc2064/tools/xc2064pack TEST1.txt -o T.rbt --compare TEST1.RBT   # Text -> Bitstream, Vergleich
cd arch/xc2064 && python3 -m xc2064db                            # Abdeckung und Gegenproben der Datenquellen
arch/xc2064/test/bitstreams.sh                                   # alles für alle XACT-Bitstreams und TEST1.RBT
```

### Taktpuffer-Eingänge (MAKEBITS)

Shirriff dekodiert die Eingangs-Muxe der beiden Taktpuffer nicht, und kein XACT-Bitstream benutzt einen
Puffer. Quellen und Codes stammen deshalb aus MAKEBITS (XACT 5.2.0) als Orakel, nur über seine normalen
Ein- und Ausgaben:

1. XACT nennt die Pins der Puffer `CLK.AA.I`/`CLK.AA.O` (GCLK) und `CLK.II.I`/`CLK.II.O` (ACLK).
   `XDELAY -convert` routet die Netze eines LCA neu. Je ein Netz von jedem der 128 CLB-Ausgänge und 58 Pads in
   jeden Puffer zeigt, über welche Kreuzung XACT den Puffer erreicht, und MAKEBITS macht daraus Bits.
2. MAKEBITS liest von einem Netz nur die G-Lagen (`Program {16G156}`, die Namen in `NProgram` nicht) und
   meldet Stellen, die es nicht programmieren kann. Ein LCA mit allen Stellen eines Rechtecks um jeden
   Puffer ergibt die programmierbaren, und weil dabei mehrere Quellen desselben Muxes an sind, nennt
   MAKEBITS alle seine Pips mit Namen. Je ein LCA mit genau einem dieser Pips ergibt dessen Code.
3. Den Quarzoszillator routet XDELAY als `OSC.II.O:CLK.II.I`; in das allgemeine Routing kommt er nicht.

| Mux | Code | Quelle | XACT | Kreuzung |
|---|---|---|---|---|
| `CLK.AA.I` (GCLK, Bits 0–5) | 63 | `row.A.local.3` (Grundstellung) | `row.A.local.3:CLK.AA.I` | 16G164 |
| | 30 | P11 | `CLK.AA.I:PAD58.I` | 16G149 |
| | 29 | P9 | `CLK.AA.I:PAD1.I` | 16G156 |
| | 27 | `col.A.local.3` | `col.A.local.3:CLK.AA.I` | 8G157 |
| | 23 | `col.A.long.3` | `col.A.long.3:CLK.AA.I` | 11G157 |
| | 15 | `row.A.long.3` | `row.A.long.3:CLK.AA.I` | 16G161 |
| `CLK.II.I` (ACLK, Bits 0–7) | 255 | `row.I.local.2` (Grundstellung) | `row.I.local.2:CLK.II.I` | 165G9 |
| | 222 | P46 | `PAD29.I:CLK.II.I` | 168G13 |
| | 221 | `col.I.long.2` | `col.I.long.2:CLK.II.I` | 170G13 |
| | 219 | `col.I.local.2` | `col.I.local.2:CLK.II.I` | 173G13 |
| | 215 | P43 | `CLK.II.I:PAD30.I` | 165G14 |
| | 207 | `row.I.long.1` | `row.I.long.1:CLK.II.I` | 165G12 |
| | 63 | Quarzoszillator (`OSC`, kein Bel) | `OSC.II.O:CLK.II.I` | 167G5 |

Code = Summe Bit n · 2^n, 1 heißt nicht programmiert. Bit 5 schaltet eine der Quellen an Bit 0–4 zu (aktiv 0,
je genau eins), ohne programmiertes Bit gilt die Grundstellung, der Oszillator programmiert nur die Bits 6
und 7. Ein Puffer treibt seine Taktleitung also immer, ohne Taktnetz aus der Grundstellung. Bis dahin
hatte nextpnr ACLK (`row.I.clk`) über die PIPs der long.2 als freien Leitungsweg benutzt; in `bcd7seg.v`
ergab das mit den neuen Codes ein Netz mit zwei Treibern. Diese PIPs sind jetzt gerichtet (ACLK → long.2),
XACT nennt sie entsprechend `col.D.long.2:CLK.II.O`. Am Chip geprüft ist nichts davon (es gibt keinen);
die Codes geben XACTs eigenes Modell wieder.

**Gegenprobe mit MAKEBITS:** `tools/xc2064lca` schreibt eine Konfiguration von nextpnr als LCA-Datei (Netze
aus dem Zusammenhang der Pips, an den Taktpuffern getrennt, mit den G-Lagen jedes Elements; je Block Base,
Config und Equate; Pads mit XACTs Namen `PADn`). MAKEBITS macht daraus einen Bitstream, der mit dem von
`xc2064pack` übereinstimmen muss, bis auf Puffer, deren Richtung das Routing nicht festlegt (`--free-bidi`):

```bash
python3 arch/xc2064/tools/xc2064lca design.cfg.txt -o DESIGN.LCA   # dann in DOSBox: MAKEBITS -B DESIGN < NUL
python3 arch/xc2064/tools/xc2064pack design.cfg.txt -o design.rbt --compare DESIGN.RBT --free-bidi
```

Ergebnis (17.10.2026) für 43 Läufe: aus dem Regressionstest je Beispiel der Standard-Seed mit und ohne PCF
(damals ohne Taktpuffer), mit den Taktpuffern (damals `--vopt clkbuf`) mit und ohne PCF und das PD48 (40),
dazu 3 einer Variante von `bcd7seg.v`. 2 Bitstreams sind bitgleich, die übrigen 41 weichen nur in 552 Bits
von Repowering-Puffern ab, und zwar nur auf Segmenten, deren Richtung das Routing nicht festlegt.
Alle Pips, Switch-Verbindungen, Muxe (auch beide Taktpuffer, GCLK an den K-Muxen in `inreg.v`), CLBs
mit ihren Gleichungen, IOBs und Optionen setzt MAKEBITS genau wie `xc2064pack`. Ebenso die 4 Läufe mit
Takten an P11 und P46 aus Stufe 12 (`blinky.v` mit dem Takt an P11, `latch_sr.v` mit `clk` an P46 und
`en` an P11, mit `clk` an P9 und `en` an P11 sowie ohne PCF im PG68): 1 bitgleich, 3 bis auf Puffer
ohne vom Routing festgelegte Richtung.

## Ausbaustufen

- **Gelatchte Eingänge an `inout`-Ports** (`XC2000_IOBUF` mit FF im Eingang): XACT kann das, das Modell
  legt bisher nur reine Eingänge ins IOB.
- **FGM tiefer suchen**: `xc2064_fgm` fasst bisher nur den D-LUT mit LUTs direkt davor zusammen. Schnitte
  über mehrere Ebenen (oder FGM schon vor `abc`) fänden mehr Fälle.
- **Echter Bitstream**: [`XC2064-def.txt`](https://github.com/shirriff/xc2064) beschreibt alle 11.360
  Konfigurationsbits (LUT-Inhalte, IOB-Optionen, PIPs, Switch-Matrizen). Für ladbare Bitstreams müssen
  die PIPs des Modells genau den PIPs des Originals entsprechen. Dafür entsteht der Routing-Graph aus
  diesen Daten, mit Shirriffs Leitungsnamen. Der Bitstream entsteht dann wie bei iCE40, ECP5 und
  GateMate in zwei Schritten (umgesetzt in Stufe 5, siehe [Bitstream](#bitstream)):
  1. nextpnr schreibt mit `--vopt out=<Datei>` eine lesbare Textdatei: die benutzten Pips und die
     Konfiguration jedes Bels (LUT-Inhalte, Muxe, IOB-Modus) mit Shirriffs bzw. XACTs Namen.
  2. Ein eigenes Tool in `arch/xc2064` (`xc2064pack`, Python) macht daraus die RBT- bzw. BIT-Datei,
     `xc2064unpack` den Rückweg. Die Tabelle Pip bzw. Bel-Option → Bit(muster) gehört ins Pack-Tool,
     nicht in nextpnr.

  So bleibt die Datei zwischen den Schritten lesbar und vergleichbar, und `xc2064unpack` übersetzt echte
  Bitstreams wie Shirriffs `TEST1.RBT` (mit `TEST1.LCA`) zurück in Pips und Bel-Konfiguration.
  `xc2064pack` schreibt RBT genau im Format von XACT. Das Ziel ist, dass der STM32-Lader aus
  [dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026) die Dateien in einen echten
  XC2064-PD48 laden kann (Erfolg: D/P-Pin High); dafür gibt es das Gehäuse PD48 neben PC68.

  Stufen:
  1. erledigt: Datenpaket `xc2064db`, `xc2064unpack` auf Bitebene, Test mit den XACT-Bitstreams (siehe
     [Datenquellen](#datenquellen-und-bitstream-werkzeuge))
  2. erledigt: CLB-Feld aus den Daten (`xc2064db.graph`): Kanäle (senkrecht 5 Einzelsegmente, waagerecht 4),
     Switch-Matrizen mit dem echten Muster, Long Lines, alle PIP-Kreuzungen, CLB-Eingänge mit allen Quellen
     und Mux-Codes, X/Y über ihre PIP-Bits; Gegenprobe mit `TEST1.LCA`. `xc2064unpack` zählt, welche
     dekodierten Pips der Graph kennt (`TEST1.RBT`: 124 von 127, die übrigen an IOBs). Die Router-Timeouts
     sind damit verschwunden
  3. erledigt: IOBs aus `iob.js` (`xc2064db.iobmux`): Ausgangs- und T-Multiplexer mit Mux-Codes,
     Eingang über PIP-Bits, an beiden Kanälen am Pad, T aus 2 lokalen Leitungen und 2 Long Lines,
     an/aus/Tristate als Konfiguration (konstantes T faltet `pack()`), beide IOBs rechts mit X/Y. Alle
     PIP-Bits liegen jetzt im Graphen, ebenso alle 127 Pips und Switch-Verbindungen von `TEST1.RBT`; die
     GUI zeichnet die IOB-Pins aus den Pips. Der längste Lauf im Regressionstest braucht 80
     Router-Iterationen
  4. erledigt: Repowering-Puffer aus den Bidi-Bits (Richtung mit den XACT-Bitstreams belegt, im Routing
     abgeleitet), Taktpuffer als Pips mit den Bits ihrer Eingangs-Muxe (Codes seit Stufe 11, Takt an
     P9/P43 nur über den Puffer), Konstanten ohne erfundene Pips (in LUT-Inhalte gefaltet oder
     Konstanten-LUT), Timing von CLB und IOB aus den Data Books 1993 (-50) und 1994 (-70/-100/-130),
     Interconnect als RC-Modell. Offen: Zahlen für das Interconnect
  5. erledigt: Konfiguration von CLB und IOB dekodiert (`xc2064db.blocks`, mit `TEST1.LCA` geprüft),
     `--vopt out=`, `xc2064pack` im RBT-Format von XACT (alle XACT-Bitstreams bitgenau im Rundlauf),
     `xc2064netlist` und der Rundlauf im Regressionstest (Text → RBT → zurück → Netzliste → formaler
     Vergleich, 42 von 42), Gehäuse PD48. Die Taktpuffer benutzte nextpnr nur mit `--vopt clkbuf` (bis
     Stufe 11 ließ sich ein so geroutetes Design nicht packen, seit Stufe 12 sind sie Standard)
  6. erledigt: Mux-Modus FGM: Primitiv `XC2000_FGM`, Bel `FGM` auf den Leitungen von F, G und FG,
     `pack()` und Legalität (beide Tabellen mit eigenen Eingängen, Q an Eingang 3, festes S wird LUT3),
     `--vopt out=` mit `BASE:FGM`, `xc2064netlist`, der yosys-Pass `xc2064_fgm` und das Beispiel
     `shiftreg.v` (8 FGM statt 9 LUT3 und 7 LUT4, 8 statt 16 CLBs)
  7. erledigt: gelatchte Eingänge: die vier K-Muxe aus `iob.js` im Datenpaket und im Graphen (Taktleitung
     je Seite, `mux P9.K …` im Textformat statt eines Feldes K), Primitiv `XC2000_INFF` mit Bel-Pin K,
     gleicher Takt je Seite als Legalitätsregel, Timing T_LI/T_PL/T_LP, der yosys-Pass `xc2064_iobff`,
     `xc2064netlist` und das Beispiel `inreg.v`; die GUI zeichnet FF, Eingangsmultiplexer, Taktleitungen
     und K-Muxe
  8. erledigt: Timing des Speicherelements als Variante je Zelle (FF steigend/fallend, Latch mit
     Transparenz D → Q aus T_ITO, Set/Reset → Q aus T_RIO/T_RLO, Bögen nur ohne kombinatorische Schleife)
     und die Gehäuse PC44 und PG68 (Pin-Tabellen beider Data Books verglichen, im Regressionstest je
     Design ein Lauf in PD48, PC44 und PG68)
  9. erledigt: Regressionstest parallel (höchstens 10 Läufe, 85 Läufe in knapp 1 min) und die
     unabhängige Gegenprobe mit Shirriffs Decoder (QuickJS, `xc2064shirriff`) in `run.sh` und
     `bitstreams.sh`: alle XACT-Bitstreams und alle erzeugten Bitstreams dekodiert er wie das Paket
  10. erledigt: größere Testdesigns (`uart_tx.v` 46 CLBs, `ampel.v` 19, `bcd7seg.v` 54) mit PCF. Unter
     Last gefunden und behoben: der Placer fand für dichte Designs keine legale Platzierung (LUT3-Paare in
     `pack()`), CLBs mit drei nach außen gehenden Signalen waren erlaubt (neue Regel: höchstens X und Y),
     die Q-Rückführung einer G-LUT lief über das Routing (jetzt Eingang 3), yosys kodierte Zustandsautomaten
     um (jetzt `-nofsm`) und der Vergleich scheiterte an einem ROM im RTL (`proc -norom`). Grenze: ab etwa
     90 % belegter CLBs braucht router2 im Debug-Build Minuten oder findet in 300 s kein Ende
  11. erledigt: Codes der Taktpuffer-Eingänge mit MAKEBITS als Orakel (siehe
     [Taktpuffer](#taktpuffer-eingänge-makebits)): `iobmux.clkmuxes` mit 6 bzw. 7 Quellen, im Graphen alle
     außer dem Oszillator, im Textformat `mux CLK.AA.I …`, damit dekodiert das Paket alle benutzten Bits.
     Mit `--vopt clkbuf` geroutete Designs lassen sich packen (im Regressionstest je Design mit und ohne
     PCF). Die PIPs von ACLK auf die long.2 sind gerichtet. `xc2064lca` schreibt eine Konfiguration als
     LCA für MAKEBITS; iob.js-Einträge ohne Leitung (X/Y direkt ans Pad, GCLK an P9.O und den K-Muxen)
     haben dafür jetzt ihre Kreuzung. `xc2064db.bitstream` liest auch RBT-Dateien von MAKEBITS 5.2.0
  12. erledigt: Taktpuffer als Standard. `--vopt noclkbuf` schaltet sie ab, `--vopt clkbuf` bleibt erlaubt
     und ändert nichts mehr. P11 und P46 sind weitere Pads von GCLK bzw. ACLK: `pack()` legt Takte ohne Pin
     dorthin, wenn P9 bzw. P43 belegt oder nicht bebondet ist (PG68: ACLK über P46), und `preRoute()` führt
     auch dort einen Takt, der nur Speicherelemente taktet, ganz über den Puffer (zwei solche Takte an
     einem Puffer: der mit den meisten Speicherelementen bekommt ihn). Im Regressionstest laufen die beiden
     Zusatzläufe je Design ohne Puffer (`noclkbuf`), alle anderen müssen einen benutzen; MAKEBITS setzt
     Takte an P11 und P46 wie `xc2064pack`. Damit hängt jeder Bitstream mit einem Takt vom Pad an den
     Puffer-Codes aus MAKEBITS; wer für einen ersten Versuch am Chip nur Bits programmieren will, die auch
     XACT-Bitstreams benutzen, nimmt `--vopt noclkbuf`

  Offen auf dem Weg zum geladenen Chip (alles braucht einen echten XC2064): der erste Versuch mit dem
  STM32-Lader (D/P-Pin) und die Flanke des IOB-FF (laut Data Book steigend) sowie Shirriffs K-Mux-Codes.
  Die Codes der Taktpuffer stammen aus XACTs Modell, nicht vom Chip.

  Nach jeder Stufe muss `test/run.sh` für alle Beispiele bestehen (Netz, Pips und seit Stufe 5 Bitstream). Die GUI behält CLB und
  IOBs im Datenblatt-Stil, nur die Kanäle folgen der Lage der Leitungen bei Shirriff.
  Weitere Vorarbeit: [JohnDMcMaster/project2064](https://github.com/JohnDMcMaster/project2064).
