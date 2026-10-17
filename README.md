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
  Multiplexer und PIPs der IOBs stammen
- [rates37/openxc2064](https://github.com/rates37/openxc2064) mit Bitstreams aus Xilinx' XACT
- Xilinx *The Programmable Logic Data Book* 1994 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1994_Xilinx_Programmable_Logic_Data_Book.pdf)),
  XC2000-Abschnitt S. 2-216 bis 2-222: Lieferformen und die Timing-Tabellen von CLB und IOB (-70, -100, -130)
- dasselbe von 1993 ([bitsavers](https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/xilinx/_dataBooks/1993_Xilinx_Programmable_Logic_Data_Book.pdf)),
  S. 2-208 bis 2-214: dieselben Tabellen mit -50, -70 und -100

Beide Repos sind Submodules unter `arch/xc2064` (siehe [Datenquellen](#datenquellen-und-bitstream-werkzeuge)):

```bash
git submodule update --init arch/xc2064/shirriff-xc2064 arch/xc2064/openxc2064
```

## Was nachgebildet ist

| Element | Modell | Quelle / Abweichung |
|---|---|---|
| Raster | 8×8 CLBs (X1Y1…X8Y8) plus IO-Ring. Shirriffs 9×9 Kacheln AA…II entsprechen X1Y1…X9Y9. Jede Kachel enthält die Kanäle oberhalb und links ihrer CLB, die 9. Spalte/Zeile nur Routing und Pads | Shirriff |
| Routing-Graph | Aus den Daten gebaut (`xc2064db.graph`): jeder Pip ist ein PIP-Bit, ein Magic-Bit einer Switch-Matrix oder ein Mux-Code eines CLB-Eingangs bzw. eines IOB-Multiplexers, die Leitungen tragen Shirriffs bzw. XACTs Namen. Einzige Ausnahme: die Eingänge der beiden Taktpuffer (Bits bekannt, Code nicht) | `XC2064-def.txt`, `draw.js`, `clb.js`, `iob.js`; geprüft mit `TEST1.LCA` (siehe [Datenquellen](#datenquellen-und-bitstream-werkzeuge)) |
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
| Taktnetze | GCLK (`CLK.AA.O` oben und `col.*.clk` je Spalte) auf B und K jeder CLB, ACLK (`row.I.clk` unten) über PIPs auf die senkrechten long.2 (Spalte A: long.4) und von dort auf K, B oder C. Den GCLK-Puffer treibt P9, den ACLK-Puffer P43, als Pip mit den Bits ihrer Eingangs-Muxe `CLK.AA.I` (6) bzw. `CLK.II.I` (8). Welcher Code das Pad wählt und welche anderen Quellen es gibt, ist offen: Shirriff dekodiert diese Muxe nicht, und keiner der XACT-Bitstreams benutzt einen Taktpuffer. Deshalb sind die Puffer nur mit `--vopt clkbuf` benutzbar (dann läuft ein Takt an P9/P43, der nur Speicherelemente taktet, ganz über seinen Puffer, und `pack()` legt Takte ohne Pin an P9/P43), und so geroutete Designs lassen sich nicht in einen Bitstream übersetzen. Ohne die Option läuft ein Takt wie jedes Signal, an K über die senkrechte long.2 der Spalte (so taktet XACT in `COUNTER.BIT`) | Datenblatt *Longlines*, Bild 8b |
| Konstanten | Keine Konstanten-Leitung, wie im Original: `pack()` faltet einen konstanten LUT-Eingang in den LUT-Inhalt, lässt Set/Reset = 0 weg und setzt für alles Übrige (konstanter Pad-Ausgang, Set = 1, …) eine LUT mit festem Inhalt ein | – |
| Gehäuse | `--vopt package=PC68` (Standard, alle 58 Pads, Pin = Pad) oder `PD48` (48-Pin-DIL, 40 Pads; den XC2064 gab es so nur als -50). PCF und LOC nennen den Pin des Gehäuses, der Placer nimmt nur bebondete Pads | *Configuration Pin Assignments* und *Component Availability* im Data Book 1994 (S. 2-214, 2-216; 1993 ebenso, S. 2-208); `xc2064db/packages.py` |
| IOBs | **58 Pads mit PLCC68-Namen** (Bel `P9` usw.), je Pad-Kachel bis zu zwei. Alle Verbindungen aus `iob.js`, an den Leitungen **beider Kanäle** am Pad (parallel und senkrecht zum Rand): Ausgang zum Pad (Bel-Pin I, im Datenblatt „O“) über einen Multiplexer mit Mux-Code aus 6–9 Quellen (Einzelsegmente, Long Lines, X/Y der Rand-CLB, an P9 GCLK, an P43 ACLK). Tristate T (1 schaltet den Treiber ab) über einen Multiplexer aus 2 Einzelsegmenten und 2 Long Lines des Kanals parallel zum Rand. Eingang vom Pad (Bel-Pin O) über PIP-Bits auf 5–7 Leitungen und fest auf Eingänge der Rand-CLB. Der Modus des Ausgangstreibers ist Konfiguration (Code des T-Multiplexers), kein Pip: an (`XC2000_OUTBUF`), aus (`XC2000_INBUF`) oder Tristate (`XC2000_TOBUF`, `XC2000_IOBUF`, T geroutet). Direktverbindungen: rechts nehmen beide Pads X und Y einer CLB der Spalte H (das erste die daneben, das zweite die darüber); oben treibt das erste Pad A und B, das zweite nimmt X der CLB links; unten treibt das erste Pad C und D, das zweite nimmt X; links treibt das zweite Pad B der CLB darüber, P24 B der CLB HA. Das IOB oben verhält sich damit wie eine CLB darüber, das unten wie eine darunter | `iob.js`; Datenblatt, Abschnitte *I/O Block* und *Direct Interconnect*. Gelatchte Ein-/Ausgänge nicht modelliert. 8 Kreuzungen in `iob.js` ohne PIP-Bit (`col.A.io2` an P9 und den zweiten Pads links) und der Eingang von P43 in den ACLK-Puffer (`@aclk_in`) fehlen |
| Timing | Geschwindigkeitsstufen über den Gerätenamen: `XC2064-50`, `-70`, `-100`, `-130` (ohne Zusatz -70; die Zahl ist die Umlaufrate eines FF in MHz). CLB und IOB nach den Tabellen des Data Books, bei -70: T_ILO 10 ns (Eingang bis Ausgang, im Modell 6 ns Funktion = T_QLO plus 4 ns Ausgangstreiber), T_CKO 10 ns (6 ns Clock-to-Q plus Treiber), T_ICK 7 ns (Setup an D also 1 ns), Takt über C 3 ns und über G 4 ns später als über K (aus T_CCO, T_CIO), Pad bis Eingang T_PID 6 ns, Ausgang bis Pad T_OP 9 ns, T bis Pad 15 ns. Interconnect als RC-Kette: jeder Schalter (Switch-Matrix, PIP, Eingangs-Mux) ist ein Widerstand vor der Kapazität der Leitung dahinter, die Kette beginnt an jedem Treiber neu (CLB-Ausgang, Taktpuffer); bei -70 kostet ein Einzelsegment hinter einem Schalter etwa 0,5 ns, eine Long Line 4 ns, der Taktpuffer 4 ns, die anderen Stufen im Verhältnis von T_ILO | Xilinx *Programmable Logic Data Book*, XC2000 *CLB Switching Characteristic Guidelines* und *IOB Switching Guidelines*: -50 (die einzige Stufe im PD48) aus dem von 1993 (S. 2-213, 2-214), -130 aus dem von 1994 (S. 2-221, 2-222), -70 und -100 stehen in beiden gleich. Bei -50: T_ILO 15, T_QLO 8, T_CKO 15, T_ICK 9, T_CCO 19, T_CIO 27, T_PID 8, T_OP 12, T_THZ/T_TON 20 ns. Für das Interconnect nennt das Buch keine Zahlen, nur das RC-Modell (*Interconnect Performance*): R, C und der Taktpuffer sind Schätzungen. Die Repowering-Puffer beenden die RC-Kette im Original, im Modell nicht (eher zu langsam). Set/Reset und das transparente Latch haben keine eigenen Bögen |

Nicht modelliert: gelatchte IOBs.

### Regeln in `nextpnr/xc2064.cc`

`isBelLocationValid` prüft je CLB:

1. FG (4 Variablen) und F/G (3 Variablen) schließen sich aus.
2. Das Speicherelement bekommt seine Daten nur von F bzw. FG derselben CLB.
3. Alle Eingänge (LUT-Pins, Takt, Set, Reset) lassen sich über die Multiplexer des Originals versorgen,
   und A–D führen dabei je höchstens ein Signal. Das ist eine exakte Zuordnungsprüfung (Backtracking).
   Interne Quellen (Q, F, G) und K (von long.2 oder GCLK) belegen keinen der Eingänge.

`pack()` hält LUT und FF als Cluster zusammen. Liegt der eigene FF-Ausgang Q nicht an Eingang 3 des
LUTs, tauscht `pack()` die Eingänge und permutiert INIT, damit die Q-Rückführung genutzt wird. Ein
unbelegter LUT-Eingang liest im Chip trotzdem eine Leitung (die Grundstellung seines Muxes); `pack()`
macht den LUT-Inhalt daher unabhängig von ihm.

Ein konstantes T ist im Original kein Signal, sondern der Modus des IOB (Code des T-Multiplexers), und
der Routing-Graph hat dafür keine Pips. `pack()` macht deshalb aus `XC2000_TOBUF`/`XC2000_IOBUF` mit
T = 0 einen `XC2000_OUTBUF` (beim `IOBUF` lesen die Nutzer von O dann direkt I) und mit T = 1 einen
`XC2000_INBUF` (Hinweis im Log).

Die Primitive heißen mit dem Familienpräfix `XC2000_` (wie `CC_` bei GateMate), damit sie sich nicht
mit Zellen anderer Bibliotheken verwechseln lassen: `XC2000_LUT3`, `XC2000_LUT4`, `XC2000_DFF` und die
IO-Puffer `XC2000_INBUF`, `XC2000_OUTBUF`, `XC2000_TOBUF` (Tristate-Ausgang) und `XC2000_IOBUF`
(bidirektional, wie `CC_TOBUF`/`CC_IOBUF` bei GateMate). Die Bel-Typen in der Chip-Datenbank bleiben
kurz (`LUT3`, `LUT4`, `DFF`, `IOB`), `getBelBucketForCellType()` ordnet sie zu. Zum Gegenstück in
yosys siehe unten.

Pins stehen in einer **PCF-Datei** wie bei iCE40 (`set_io [-nowarn] <Port> <Pin>`, Busse als
`leds[0]`, Pins als Pin des Gehäuses: P2…P68 im PC68, P1…P48 im PD48), die nextpnr mit
`--vopt pcf=<Datei>` liest. `flow.sh` nimmt `design.pcf` neben `design.v` automatisch, `PCF=…` wählt eine
andere. Ohne Eintrag entscheidet der Placer. Mit `--vopt clkbuf` legt `pack()` Takte selbst an die
Taktpads: das Netz mit den meisten Speicherelementen an P9 (GCLK), das nächste an P43 (ACLK), soweit
diese Pads frei sind. Ein Takt, der per Constraint an einem anderen Pad liegt, bleibt dort (Hinweis im
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
- `abc -lut 3:4` bewertet einen LUT4 mit den Kosten zweier LUT3.
- `dfflegalize` erlaubt FF und Latch mit beiden Taktpolaritäten und asynchronem Set/Reset.
- Der Pass `xc2064_fgm` (nach dem LUT-Mapping, abschaltbar mit `synth_xc2064 -nofgm`) fasst den LUT vor
  einem Speicherelement mit LUTs davor zusammen, die nur ihn speisen, wenn das Ganze eine Funktion von
  genau 5 Signalen ist, darunter das eigene Q, und die Form `S ? f(a, c, x) : g(a, c, Q)` hat (oder F und
  G vertauscht). Dann wird daraus ein `XC2000_FGM`: S an B, a und c an Eingang 1 und 2 beider Tabellen, x
  bzw. Q an Eingang 3. Mit weniger Signalen reicht ein LUT4, ohne Q bringt FGM nichts. Bisher prüft der
  Pass nur LUTs direkt vor dem D-LUT (eine Ebene)
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
Rundlauf über den Bitstream (Stufe 5) dauert der ganze Test etwa 4 min, mit `shiftreg.v` (Stufe 6, 56
Läufe) gut 6 min.

## Ablauf

```bash
scripts/build-nextpnr.sh debug              # nach Änderungen an nextpnr/* (inkl. Generator)
arch/xc2064/flow.sh                         # Synthese + Place & Route mit examples/blinky.pcf (5 MHz, FREQ=… ändert es)
SEED=1 arch/xc2064/flow.sh                  # mit festem nextpnr-Seed (ohne SEED: nextpnr-Standard)
arch/xc2064/flow.sh arch/xc2064/examples/latch_sr.v   # anderes Design
arch/xc2064/flow.sh --gui                   # mit nextpnr-GUI: Pack, Place, Route über die Werkzeugleiste
arch/xc2064/test/run.sh                     # Regressionstest (siehe unten)
arch/xc2064/test/bitstreams.sh              # Datenquellen, xc2064unpack und xc2064pack mit XACT-Bitstreams prüfen
nextpnr-himbaechel --device XC2064 --json build/flows/xc2064/blinky.pnr.json --gui   # geroutetes Ergebnis ansehen
```

### Bitstream

```bash
arch/xc2064/flow.sh arch/xc2064/examples/blinky.v --vopt out=build/flows/xc2064/blinky.cfg.txt
python3 arch/xc2064/tools/xc2064pack build/flows/xc2064/blinky.cfg.txt -o build/flows/xc2064/blinky.rbt
python3 arch/xc2064/tools/xc2064unpack build/flows/xc2064/blinky.rbt -o blinky.txt     # Rückweg als Text
python3 arch/xc2064/tools/xc2064netlist build/flows/xc2064/blinky.rbt --meta build/flows/xc2064/blinky.cfg.txt -o blinky.bit.v
```

Für den XC2064-50PD48 kommen `--device XC2064-50 --vopt package=PD48` und eine PCF mit den DIL-Pins dazu;
`xc2064pack` übernimmt das Gehäuse aus der Textdatei in den RBT-Kopf (`2064PD48`). Die RBT-Datei hat
genau den Aufbau von XACT (7 Textzeilen, Kopf, 160 Rahmen, `11111111`, CRLF), für den STM32-Lader aus
[dhr0000001/XC2064-in-2026](https://github.com/dhr0000001/XC2064-in-2026); `-o datei.bit` schreibt
stattdessen die binäre Form.

Ein schon geroutetes `*.pnr.json` lädt nextpnr in der GUI direkt. Auf der Kommandozeile braucht es
`--no-pack`, das Ergebnis ist schon gepackt. Eine andere Geschwindigkeitsstufe wählt der Gerätename,
etwa `--device XC2064-50` für den XC2064-PD48 (ohne Zusatz -70).

| Beispiel | Inhalt | Ergebnis |
|---|---|---|
| `examples/blinky.v` | 16-Bit-Zähler, Pins in `blinky.pcf` (Takt an P9, alles am oberen Rand) | 20 LUT3, 7 LUT4, 16 FF, bei -70 je nach Seed 14,0–14,6 MHz (Standard-Seed 14,4 MHz, `flow.sh --seed 1` oder `SEED=1 arch/xc2064/flow.sh` 14,5 MHz), bei -50 9,7 MHz (im PD48 9,6 MHz). Ohne PCF (`PCF=/dev/null`) je nach Seed 13,8–14,4 MHz. Die Werte verschieben sich mit jeder Änderung an Routing-Graph und Timing. Der kritische Pfad sind die LUT-Ebenen der Zähler-Logik, eine Carry-Kette hatte erst der XC4000 |
| `examples/latch_sr.v` | FF mit fallender Flanke, FF mit asynchronem Set/Reset, Latch, Pins in `latch_sr.pcf` | 3 Speicherelemente mit `CLKINV`, `S`/`R` bzw. `LATCH`. Mit `--vopt clkbuf` und ohne PCF kommt `clk` an P9 und das Latch-Enable `en` an P43 |
| `examples/tristate.v` | 4-Bit-Bus (`inout`) mit Low-aktivem `oe_n`, Tristate-Ausgang `tout` mit `en_n`, Pins in `tristate.pcf` (alles am oberen Rand) | 4 `XC2000_IOBUF`, 1 `XC2000_TOBUF`, 7 LUT3, 1 LUT4, 8 FF, bei -70 je nach Seed 53–57 MHz (-50: 39 MHz). T aller Bus-Bits hängt ohne Logik am Pad von `oe_n` und läuft über eine Long Line des oberen Randkanals (die T-Quellen dort: 2 Einzelsegmente und 2 Long Lines). Mit High-aktivem Enable (Inverter in einer CLB, deren Ausgänge die waagerechten Long Lines nicht erreichen, also nur über die Spuren zu den T) war der Bus dort nicht routbar |
| `examples/shiftreg.v` | 8-Bit-Schieberegister mit parallelem Laden (`load`, `din`) und Enable (`en`, `sin`), Pins in `shiftreg.pcf` (Steuerung und `din` oben, `q` rechts) | 8 `XC2000_FGM`, 8 FF in 8 CLBs: jedes Bit ist `load ? din[i] : (en ? q[i-1] : q[i])`, F liest `din[i]` an D, G `en`, `q[i-1]` und das eigene Q, B = `load` wählt. Bei -70 je nach Seed 54,6–57,1 MHz. Mit `synth_xc2064 -nofgm` 9 LUT3 und 7 LUT4 in 16 CLBs, 35,1 MHz (Standard-Seed mit PCF) |

In VS Code laufen die allgemeinen Tasks *Arch: Flow ausführen* und *Arch: Flow mit nextpnr-GUI* sowie
die Debug-Konfigurationen für Architekturen (Run and Debug). Als Namen jeweils `xc2064` eingeben.

### Regressionstest

`test/run.sh [design.v …]` synthetisiert jedes Beispiel (ohne Argument alle `examples/*.v`), routet es
mit dem nextpnr-Standard-Seed und den Seeds 1–6, mit und ohne PCF, und prüft jeden Lauf. Zeilen
`// erwartet: <Zelltyp> <Anzahl>` im Design prüfen schon die Synthese (`shiftreg.v` verlangt 8
`XC2000_FGM`, fällt der Pass aus, schlägt der Test fehl):

| Spalte | Prüfung |
|---|---|
| PnR | nextpnr endet ohne Fehler innerhalb von `TIMEOUT` Sekunden (Standard 300, router2 hat kein Abbruchlimit). Verfehltes Timing allein ist kein Fehler (`--timing-allow-fail`) |
| Netz | Die Netzliste nach dem Routing (`*.pnr.json`, also nach `pack()` mit Eingangstausch, INIT-Permutation und Konstanten) ist formal äquivalent zum RTL |
| Pips | `test/extract_netlist.py` gewinnt die Netzliste allein aus den belegten Bels und den benutzten Pips zurück, also aus dem, was ein Bitstream festhält. Jeder Eingang muss am Treiber hängen, den die Netzliste von nextpnr vorsieht, keiner darf zwei haben, und kein benutzter Pip darf verwaist sein. Die so gewonnene Netzliste muss ebenfalls äquivalent zum RTL sein. Das deckt Platzierung und Routing mit ab |
| Bitstream | Rundlauf über den echten Bitstream: nextpnr schreibt die Konfiguration als Text (`--vopt out=`), `xc2064pack` macht daraus eine RBT-Datei, `xc2064unpack` und noch einmal `xc2064pack` geben sie bitgenau wieder, und `xc2064netlist` gewinnt allein aus der RBT-Datei (Namen von Ports und Registern aus der Textdatei) eine Netzliste zurück, die formal äquivalent zum RTL sein muss. Ein verfälschtes LUT-Bit fällt dabei auf |
| Fmax | Kleinste Frequenz aller Takte. Mit `FMIN=…` (MHz) ist ein Wert darunter ein Fehler |
| Routing | Iterationen und Laufzeit von router2, nur zur Information |

Der Vergleich läuft in yosys: `equiv_make` paart die gleichnamigen Signale (Ports und Register),
`clk2fflogic` bildet die Takte mit ihrer Flanke nach (`CLKINV` zählt also mit), und `equiv_induct`
beweist die Gleichheit für alle Eingangsfolgen. Als Modelle dienen `yosys/cells_sim.v` und für die
Konstanten-Zellen, die nextpnr bis Stufe 3 anlegte, `test/pnr_cells.v` (seit Stufe 4 sind Konstanten
gewöhnliche LUTs). Ein verändertes INIT-Bit, vertauschte
LUT-Eingänge, ein umgedrehtes `CLKINV`, ein FF statt Latch, ein gelöster Pip oder ein LUT-Eingang an
der falschen Quelle fallen jeweils auf.

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
  P9, ACLK unten waagerecht vom Pad P43.
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
Taktleitung (`CLK.AA.O` bzw. `row.I.clk`), das Kästchen dort ist der Taktpuffer; der Ausgangsmultiplexer
hat an derselben Leitung GCLK bzw. ACLK als Quelle.

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

Nicht verwendet werden XACTSTEP und die Gerätedaten von XACT.

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
| `blocks` | Konfiguration der CLBs (LUTs, Eingangsauswahl, FF/Latch, Takt, Set/Reset, X/Y), der IOBs (Eingang direkt/gelatcht) und der Optionen: Bits ↔ Felder, Grundzustand von XACT |
| `config` | Textformat der Konfiguration: Bits → Text (`decode`), Text → Bits (`encode`) |
| `netlist` | Netzliste aus einem Bitstream (Rückweg für den formalen Vergleich), Funktionsgeneratoren als `XC2000_LUT3`, `XC2000_LUT4` (BASE F) bzw. `XC2000_FGM` (BASE FGM) |
| `packages` | Gehäuse PC68 und PD48: Pin → Pad |
| `graph` | Routing-Graph: Segmente aus den Trennstellen an den Matrizen und dem Modell der fünften Leitung, Verbindungen aus PIP-, Magic- und Mux-Bits. Der Generator `nextpnr/xc2064_arch_gen.py` baut daraus die Kacheln, `xc2064unpack` prüft daran die Bitstreams |
| `lca` | `TEST1.LCA` von XACT lesen und gegen Dekodierung und Graph prüfen |

Was die Daten über das Original sagen:
- **Switch-Matrizen:** Die 98 inneren haben dasselbe Muster mit 20 Verbindungen, jeder Pin mit 5 der 7
  anderen. Die 56 am Rand haben dasselbe Muster ohne die Pins der fehlenden Seite.
- **CLB-Eingänge:** A hat 6–7 Quellen, B 10, C 8, D 6–7 und K 2.
- **IOBs:** Ausgang zum Pad aus 6–9 Quellen, T aus 4 (2 Einzelsegmente und 2 Long Lines des Kanals
  parallel zum Rand), Eingang auf 5–7 Leitungen. Die Leitungen eines Pins an den Kreuzungen
  (`io1`–`io6`, `x`, `clbl`/`clbr`/`clbw`, die Randleitungen local.0 und local.5) sind Teil des IOB und
  keine eigenen Routing-Leitungen. Der Code des T-Multiplexers trägt auch den Modus: Tristate (eine
  Quelle gewählt), Treiber immer an oder immer aus.
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
- **Abdeckung:** Von 8596 benutzten Bits dekodiert das Paket 8582: Pips, Switch-Matrizen, die Muxe von
  CLB und IOB, die Richtung der Puffer, die Konfiguration der CLBs und IOBs und die Optionen. Offen sind
  nur die 14 Bits der Taktpuffer-Eingänge `CLK.AA.I` und `CLK.II.I`: Kein Bitstream benutzt sie, ihre
  Codes lassen sich erst mit einem echten Chip bestimmen (etwa ein Zähler an GCLK, Code für Code geladen).
- **Routing-Graph:** Er enthält alle 2520 Magic-Bits und alle 1656 PIP-Bits: 806 PIPs zwischen
  allgemeinen Leitungen, 448 Ausgangs-PIPs von X und Y, 353 Eingangs-PIPs der IOBs und 49
  Verbindungspunkte der fünften Leitung. Dazu die 2064 Mux-Quellen der CLB-Eingänge und 642 der
  IOB-Multiplexer (410 Ausgang, 232 T) und die beiden Taktpuffer-Eingänge von P9 und P43 (Code
  unbekannt). Nicht im Graphen sind 9 Einträge aus `iob.js`: 8 Kreuzungen mit `col.A.io2`, für die die
  Bitkarte kein PIP-Bit hat, und `@aclk_in` an P43, das Shirriff selbst nicht auflöst.
- **Gegenprobe mit XACT:** Alle 210 Routing-Elemente, die XACT in `TEST1.LCA` nennt, stehen in der
  Dekodierung von `TEST1.RBT`. 2 davon sind Takte gelatchter IOBs (nicht dekodiert), 29 sind T-Eingänge
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
steht `11111111`.

**Textformat** (zwischen nextpnr und `xc2064pack`, Rückweg `xc2064unpack`), eine Zeile je Eintrag:

```
device XC2064
package PD48                               # Gehäuse für den RBT-Kopf (PC68 oder PD48)
clb AB BASE:FG F:A:B:C G:A:C:Q LUTF:96 LUTG:E8 X:F Y:G Q:FF SET:A RES:D CLK:K:NOT
iob P8 I:Q                                 # Eingang des IOB direkt (PAD) oder gelatcht (Q)
mux AB.A row.A.local.1                     # CLB-Eingang und gewählte Quellleitung (oder none)
mux P59.O AH.X                             # Ausgangs-Mux eines IOB: Leitung, X/Y einer CLB, GCLK oder ACLK
mux P59.T col.I.long.2                     # T-Mux eines IOB: Quelle (Tristate), on (Treiber an) oder off
pip col.B.local.5:row.B.local.3            # PIP: Kreuzung zweier Leitungen
switch AB.8.1 3-8                          # Verbindung zweier Pins einer Switch-Matrix
bidi 125G6 right                           # Repowering-Puffer: down/right (Bit 0), sonst up/left
bidi auto                                  # Richtung aller Puffer aus dem Routing (xc2064pack)
other DONE pin Pullup/No Pullup 1          # Optionen
bit CLB CLK.AA.I MuxBit: 0                 # sonst programmiertes Bit mit Namen (nur noch Taktpuffer-Eingänge)
port P9 clk input                          # (nextpnr) Port am Pad, für den Rückweg zur Netzliste
reg AB ctr[0]                              # (nextpnr) Name des Registers einer CLB, ebenso
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

## Ausbaustufen

- **Gelatchte IOB-Eingänge** mit den vier IOB-Taktmultiplexern (`iob.js`).
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
     abgeleitet), Taktpuffer als Pips mit den Bits ihrer Eingangs-Muxe (Code offen, Takt an P9/P43 nur
     über den Puffer), Konstanten ohne erfundene Pips (in LUT-Inhalte gefaltet oder Konstanten-LUT),
     Timing von CLB und IOB aus den Data Books 1993 (-50) und 1994 (-70/-100/-130), Interconnect als
     RC-Modell. Offen: die Codes von `CLK.AA.I`/`CLK.II.I` (Versuch am echten Chip) und Zahlen für das
     Interconnect
  5. erledigt: Konfiguration von CLB und IOB dekodiert (`xc2064db.blocks`, mit `TEST1.LCA` geprüft),
     `--vopt out=`, `xc2064pack` im RBT-Format von XACT (alle XACT-Bitstreams bitgenau im Rundlauf),
     `xc2064netlist` und der Rundlauf im Regressionstest (Text → RBT → zurück → Netzliste → formaler
     Vergleich, 42 von 42), Gehäuse PD48. Weil der Code der Taktpuffer-Eingänge unbekannt ist, routet
     nextpnr Takte ohne sie (`--vopt clkbuf` schaltet sie zu)
  6. erledigt: Mux-Modus FGM: Primitiv `XC2000_FGM`, Bel `FGM` auf den Leitungen von F, G und FG,
     `pack()` und Legalität (beide Tabellen mit eigenen Eingängen, Q an Eingang 3, festes S wird LUT3),
     `--vopt out=` mit `BASE:FGM`, `xc2064netlist`, der yosys-Pass `xc2064_fgm` und das Beispiel
     `shiftreg.v` (8 FGM statt 9 LUT3 und 7 LUT4, 8 statt 16 CLBs)

  Offen auf dem Weg zum geladenen Chip (beides braucht einen echten XC2064): der erste Versuch mit dem
  STM32-Lader (D/P-Pin) und die Codes von `CLK.AA.I`/`CLK.II.I`.

  Nach jeder Stufe muss `test/run.sh` für alle Beispiele bestehen (Netz, Pips und seit Stufe 5 Bitstream). Die GUI behält CLB und
  IOBs im Datenblatt-Stil, nur die Kanäle folgen der Lage der Leitungen bei Shirriff.
  Weitere Vorarbeit: [JohnDMcMaster/project2064](https://github.com/JohnDMcMaster/project2064).
