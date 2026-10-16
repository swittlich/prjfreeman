# Architektur `xc2064`: Modell des Xilinx XC2064

Der XC2064 (1985) war das erste FPGA: 64 Configurable Logic Blocks (CLBs) in einem 8×8-Raster und
58 I/O-Pins (PLCC68). Diese Architektur bildet ihn als nextpnr-Himbächel-uarch nach, mit yosys-Plugin,
Place & Route, Timing und einer vollständigen Schaltplan-Ansicht in der GUI. Einen Bitstream für echte
Chips erzeugt sie **nicht** (siehe unten).

Grundlagen:
- XC2000-Datenblatt
- Ken Shirriff, [Reverse-engineering the first FPGA chip, the XC2064](https://www.righto.com/2020/09/reverse-engineering-first-fpga-chip.html)
- sein Bitstream-Decoder [shirriff/xc2064](https://github.com/shirriff/xc2064), aus dessen `clb.js` und `iob.js`
  die Eingangsmultiplexer der LUTs, die Optionen des Speicherelements und die Pad-Tabelle stammen

## Was nachgebildet ist

| Element | Modell | Quelle / Abweichung |
|---|---|---|
| Raster | 8×8 CLBs (X1Y1…X8Y8) plus IO-Ring. Shirriffs 9×9 Kacheln AA…II entsprechen X1Y1…X9Y9. Jede Kachel enthält die Kanäle oberhalb und links ihrer CLB, die 9. Spalte/Zeile nur Routing und Pads | Shirriff |
| Kanäle, Switch-Matrizen | 9 horizontale und 9 vertikale Kanäle, an ihren 9×9 Kreuzungen je 2 Switch-Matrizen mit 8 Pins (2 je Seite), jeder Pin mit 5 der 7 anderen verbindbar (20 Verbindungen) | Anzahl und Verbindungszahl wie bei Shirriff, das genaue Muster ist angenommen |
| Einzelsegmente | 4 Spuren je Kanal zwischen benachbarten Switch-Matrizen | Original ähnlich |
| Funktionsgeneratoren | `F`, `G` (Primitiv `XC2000_LUT3`): Eingang 1 aus {A, B}, Eingang 2 aus {B, C}, Eingang 3 aus {C, D, **Q**} | `clb.js` |
| 4-Variablen-Modus | `FG` (`XC2000_LUT4`): Eingänge wie F/G, **B** wählt zwischen F und G (I[3]), belegt beide | `clb.js` |
| Speicherelement | `XC2000_DFF`: Flipflop oder **Latch** (`LATCH`), Takt aus **K, C oder G**, **invertierbar** (`CLKINV`), asynchrones **Set aus A oder F**, **Reset aus D oder G**, Daten aus F bzw. FG | `clb.js`; Vorrang Reset vor Set angenommen |
| Ausgänge | X, Y je aus Q, F oder G, beide in den vertikalen Kanal **rechts** der CLB: X an V2, V4 und die 1. vertikale Long Line, Y an V1, V3 und die 2. | `clb.js`; Shirriffs Bitmap (`XC2064-def.txt`, `draw.js`). V5 hat das Modell nicht (4 Spuren je Kanal) |
| CLB-Eingänge A–D | A aus dem Kanal oberhalb und der Long Line der eigenen Zeile, B/C aus dem Kanal links und je einer vertikalen Long Line, D aus dem Kanal unterhalb und der Long Line der Zeile darunter, dazu die Direktverbindungen (je 6–7 Quellen) | `clb.js`; Original: 6–10 Quellen je Eingang |
| Direktverbindungen | X → C/D der CLB darüber und A/B der CLB darunter, Y → B der CLB rechts | Datenblatt, Abschnitt *Direct Interconnect* |
| Long Lines | 1 horizontale je Zeile, 2 vertikale je Spalte (auch Zeile/Spalte I am Rand), bis zu den Pads | Datenblatt, Abschnitt *Longlines* |
| Taktnetze | K aus **GCLK** (Pin P9, oben links) oder **ACLK** (Pin P43, unten rechts) | Lage der Puffer laut Datenblatt, Zuordnung zu P9/P43 angenommen |
| IOBs | **58 Pads mit PLCC68-Namen** (Bel `P9` usw.) am Kanalstück **parallel zum Rand** neben einer Rand-CLB: das erste Pad einer Kachel am eigenen Stück, das zweite am vorherigen, je bis zu zwei IOBs pro Stück. Ausgang zum Pad (Bel-Pin I, im Datenblatt „O“) aus den 4 Spuren und der Long Line des Randkanals, Tristate T aus den 4 Spuren oder fest, Eingang vom Pad (Bel-Pin O) auf Spuren und Long Line. Direktverbindungen mit der Rand-CLB: rechts nimmt das erste Pad X und Y; links treibt das zweite Pad B; oben treibt das erste Pad B und das zweite nimmt X; unten treibt das erste Pad C und D und das zweite nimmt X. Das IOB oben verhält sich damit wie eine CLB darüber, das unten wie eine darunter | `iob.js`; Datenblatt, Abschnitt *Direct Interconnect*. Gelatchte Ein-/Ausgänge nicht modelliert, am rechten Rand nimmt nur das erste Pad X/Y (laut `iob.js` auch das zweite) |
| Timing | LUT3 15 ns, LUT4 18 ns, FF 10 ns Clock-to-Q / 8 ns Setup, Pass-Transistor 2,5 ns | Größenordnung XC2064-70 |

Nicht modelliert: der Mux-Modus „FGM“ (zwei unabhängige 3-Variablen-Funktionen, B wählt) und
gelatchte IOBs.

### Regeln in `nextpnr/xc2064.cc`

`isBelLocationValid` prüft je CLB:

1. FG (4 Variablen) und F/G (3 Variablen) schließen sich aus.
2. Das Speicherelement bekommt seine Daten nur von F bzw. FG derselben CLB.
3. Alle Eingänge (LUT-Pins, Takt, Set, Reset) lassen sich über die Multiplexer des Originals versorgen,
   und A–D führen dabei je höchstens ein Signal. Das ist eine exakte Zuordnungsprüfung (Backtracking).
   Interne Quellen (Q, F, G) und K (nur für globale Takte von P9/P43) belegen keinen der Eingänge.

`pack()` hält LUT und FF als Cluster zusammen. Liegt der eigene FF-Ausgang Q nicht an Eingang 3 des
LUTs, tauscht `pack()` die Eingänge und permutiert INIT, damit die Q-Rückführung genutzt wird.

Die Primitive heißen mit dem Familienpräfix `XC2000_` (wie `CC_` bei GateMate), damit sie sich nicht
mit Zellen anderer Bibliotheken verwechseln lassen: `XC2000_LUT3`, `XC2000_LUT4`, `XC2000_DFF`,
`XC2000_INBUF`, `XC2000_OUTBUF`. Die Bel-Typen in der Chip-Datenbank bleiben kurz (`LUT3`, `LUT4`,
`DFF`, `IOB`), `getBelBucketForCellType()` ordnet sie zu. Zum Gegenstück in yosys siehe unten.

Pins stehen in einer **PCF-Datei** wie bei iCE40 (`set_io [-nowarn] <Port> <Pin>`, Busse als
`leds[0]`, Pins als PLCC68-Namen P2…P68), die nextpnr mit `--vopt pcf=<Datei>` liest. `flow.sh` nimmt
`design.pcf` neben `design.v` automatisch, `PCF=…` wählt eine andere. Ohne Eintrag entscheidet der
Placer, nur Takte legt `pack()` selbst an die Taktpads: das Netz mit den meisten Speicherelementen an
P9 (GCLK), das nächste an P43 (ACLK), soweit diese Pads frei sind. Nur von dort erreicht ein Takt K
aller CLBs, sonst belegt er in jeder CLB mit Speicherelement einen der Eingänge A–D. Ein Takt, der per
Constraint an einem anderen Pad liegt, bleibt dort (Hinweis im Log). Alternativ geht weiterhin `(* LOC="P9" *)` an einem `XC2000_INBUF`/`XC2000_OUTBUF` im
Verilog, die PCF-Datei hat Vorrang. `pack()` belegt diese Pads schon beim Packen fest (wie GateMate),
die GUI zeigt sie also direkt nach „Pack“ als belegt. Ein BEL-Attribut setzt es dabei nicht, sonst würde
der Placer die Zellen ein zweites Mal binden wollen.

yosys (`yosys/synth_xc2064.cc`):
- `abc -lut 3:4` bewertet einen LUT4 mit den Kosten zweier LUT3.
- `dfflegalize` erlaubt FF und Latch mit beiden Taktpolaritäten und asynchronem Set/Reset.
- Der Pass `xc2064_ffbuf` gibt jedem FF einen eigenen treibenden LUT.
- Die eigenen Zelltypen stehen nicht in yosys' `kernel/constids.inc`. `ID(...)` geht dafür bei
  aktuellem yosys (Twine-IdStrings) nicht, der Pass legt sie mit `design->twines().add(...)` an.

Standard-Router ist `router2`, weil das Routing knapp ist. Er sucht jedes Netz nur in dessen Bounding
Box plus einem Rand von normalerweise 3 Kacheln. Mit 4 Spuren je Kanal reicht das nicht immer: dann
wechseln sich zwei Netze an einem Draht ab, und router2 kommt nicht mehr zum Ende (er hat kein
Abbruchlimit). `preRoute()` setzt den Rand deshalb auf die Chipgröße, wenn die Einstellungen
`router2/bbMargin/x` und `/y` nicht schon gesetzt sind. Mit `--router router1` scheitern manche Seeds an
Überlastung, die Option bleibt aber möglich.

## Ablauf

```bash
scripts/build-nextpnr.sh debug              # nach Änderungen an nextpnr/* (inkl. Generator)
arch/xc2064/flow.sh                         # Synthese + Place & Route mit examples/blinky.pcf (5 MHz, FREQ=… ändert es)
SEED=1 arch/xc2064/flow.sh                  # mit festem nextpnr-Seed (ohne SEED: nextpnr-Standard)
arch/xc2064/flow.sh arch/xc2064/examples/latch_sr.v   # anderes Design
arch/xc2064/flow.sh --gui                   # mit nextpnr-GUI: Pack, Place, Route über die Werkzeugleiste
nextpnr-himbaechel --device XC2064 --json build/flows/xc2064/blinky.pnr.json --gui   # geroutetes Ergebnis ansehen
```

Ein schon geroutetes `*.pnr.json` lädt nextpnr in der GUI direkt. Auf der Kommandozeile braucht es
`--no-pack`, sonst legt das Packen die Konstanten-Zellen ein zweites Mal an.

| Beispiel | Inhalt | Ergebnis |
|---|---|---|
| `examples/blinky.v` | 16-Bit-Zähler, Pins in `blinky.pcf` (Takt an P9, alles am oberen Rand) | 20 LUT3, 7 LUT4, 16 FF, je nach Seed 4,9–6,2 MHz. Der nextpnr-Standard-Seed verfehlt das Ziel 5 MHz knapp (4,9 MHz), `flow.sh --seed 1` oder `SEED=1 arch/xc2064/flow.sh` schafft 6,0 MHz. Ohne PCF (`PCF=/dev/null`) legt `pack()` den Takt selbst an P9, je nach Seed 4,9–6,1 MHz. Der kritische Pfad sind die LUT-Ebenen der Zähler-Logik, eine Carry-Kette hatte erst der XC4000 |
| `examples/latch_sr.v` | FF mit fallender Flanke, FF mit asynchronem Set/Reset, Latch, Pins in `latch_sr.pcf` | 3 Speicherelemente mit `CLKINV`, `S`/`R` bzw. `LATCH`. Ohne PCF kommt `clk` an P9 und das Latch-Enable `en` an P43 |

In VS Code laufen die allgemeinen Tasks *Arch: Flow ausführen* und *Arch: Flow mit nextpnr-GUI* sowie
die Debug-Konfigurationen für Architekturen (Run and Debug). Als Namen jeweils `xc2064` eingeben.

### GUI

Die Grafik ist ein Schaltplan des ganzen Chips mit **allen Leitungen, Bels und Pips**. nextpnr blendet
unbenutzte Pips sonst aus, `xc2064.cc` zeichnet sie gedämpft. Nach dem Routing sind die benutzten
hervorgehoben, so dass sich jeder Pfad vom Pad über Kanäle, Switch-Matrizen und Eingangsmultiplexer bis
in die LUTs und das Flipflop verfolgen lässt. Mit der Maus über einem Pip zeigt die GUI seinen Namen.

Die Ausrichtung folgt Datenblatt und Die-Fotos: X0Y0 oben links. In den Kacheln X1Y1…X9Y9 sitzen oben
links die Switch-Matrizen SM0/SM1 (die Diagonalen darin sind ihre Pips), rechts davon bzw. darunter die
Kanäle (2 Spuren pro Matrix). Dünne Linien sind die Long Lines und die beiden Taktnetze. Am Rand
enden die Switch-Matrizen, die Kanäle laufen dort nur parallel zum Rand weiter.

Die IOBs sind wie im Datenblatt gezeichnet: außen das Pad, im Rahmen der Ausgangstreiber (Dreieck zum
Pad) mit seinem Multiplexer und dem kleineren Multiplexer für das Tristate, daneben der Eingangstreiber
(Dreieck nach innen). Ausgang, Tristate und Eingang laufen als drei Leitungen quer über das
Randkanalstück, PIP-Kästchen zeigen, an welchen Spuren und Long Lines sie geschaltet werden können.
Direktverbindungen: Am rechten Rand laufen X und Y der CLB links durch den Kanal in den
Ausgangsmultiplexer des IOB, oben und unten läuft X senkrecht in den Ausgangsmultiplexer des zweiten IOB
(dafür ist es gespiegelt gezeichnet). Der Eingang vom Pad läuft oben zu B, unten zu C und D, links zu B
der Rand-CLB, auf den Wegen, die dort sonst die Direktleitungen der fehlenden Nachbar-CLB nehmen. P9
und P43 führen ihren Eingang außerdem zum Taktpuffer von GCLK bzw. ACLK.

Eine CLB (grauer Rahmen) folgt dem Blockschaltbild im Datenblatt, von links nach rechts:

| Spalte | Inhalt |
|---|---|
| Eingänge | A, B, C, D als Zeilen von links. A kommt vom Kanal oben, D vom Kanal unten, B und C vom Kanal links |
| Kombinatorische Logik | Schienen Q, D, C, B, A, die Multiplexer der LUT-Eingänge, LUT F, LUT G und FG als Rahmen um beide mit dem F/G-Multiplexer (B wählt) |
| Verteiler | F, FG, G mit den Multiplexern für Set (oben), Daten, Takt und Reset (unten) |
| Speicherelement | D und Takt (Dreieck) links, S oben, R unten, Q rechts |
| Ausgänge | Schienen F, FG, G, Q mit den Multiplexern X und Y, beide rechts hinaus durch den Kanal (PIP-Kästchen an ihren Spuren und Long Lines) |

Wie im Datenblatt läuft A über die Logik zum Set-Multiplexer. C, das Taktsignal K von GCLK/ACLK und D
laufen unter der Logik zu Takt und Reset. F, FG und G laufen über dem Speicherelement zu den Ausgängen,
Q läuft unten herum zurück zu den LUTs. Die Direktleitungen von X laufen am rechten Rand hinauf und
hinab zu den Pins der CLB darüber bzw. darunter, Y läuft durch den Kanal weiter in die B-Zeile der CLB
rechts. Keine Leitung läuft durch ein Bauteil. Im Routing zeichnet jedes Wire seine ganze Leitung bis zu
den Kreuzungen, an denen es geschaltet werden kann, auch die Direktleitungen und die Anschlüsse der
Pads. Der Pip ist dort nur das Kästchen, wie Metall und Schalter im Chip. Markiert man ein Wire,
leuchtet also die ganze Leitung. In der CLB sind Pips ein Abgriff mit Punkt an der Schiene. Ein
benutzter Pip zeigt zusätzlich seinen Weg durch den Multiplexer. Im FG-Modus leuchten die Multiplexer
von F und G, der Rahmen und der F/G-Multiplexer.

Weil nextpnr selbst mit y nach oben zeichnet, spiegelt `xc2064.cc` die Grafik. Weil nextpnr `drawPip`
den kanonischen Draht eines Knotens übergibt (der in einer Nachbarkachel liegen kann), sucht
`local_gfx_id()` den Draht in der Kachel des Pips.

Ein Bild des ganzen Chips ohne GUI liefert ein `--post-route`-Skript mit `ctx.writeSVG("chip.svg", "scale=300")`.
Das SVG zeichnet in fester Reihenfolge, nicht nach Zustand. Deshalb kann dort eine gedämpfte Linie eine
benutzte an derselben Stelle überdecken (FG nutzt die Multiplexer von F und G). Die GUI zeichnet
Benutztes immer obenauf.

## Ausbaustufen

- **Mux-Modus FGM** (B wählt zwischen zwei unabhängigen 3-Variablen-Funktionen) als eigener Bel-Modus.
- **CLB-Eingänge A–D** mit allen Quellen des Originals (laut `clb.js` 6–10 je Eingang).
- **Gelatchte IOB-Eingänge** mit den vier IOB-Taktmultiplexern (`iob.js`).
- **Zweites IOB am rechten Rand** mit X und Y der CLB links (`iob.js`, `rightlower`).
- **Echter Bitstream**: [`XC2064-def.txt`](https://github.com/shirriff/xc2064) beschreibt alle 11.360
  Konfigurationsbits (LUT-Inhalte, IOB-Optionen, PIPs). Für ladbare Bitstreams müssten die PIPs des
  Modells genau den PIPs des Originals entsprechen. Dafür muss man den Routing-Graphen aus diesen Daten
  und der Die-Geometrie rekonstruieren. Danach kann ein `--post-route`-Python-Skript oder eine
  C++-Funktion in `xc2064.cc` die RBT-Datei schreiben.
  Weitere Vorarbeit: [JohnDMcMaster/project2064](https://github.com/JohnDMcMaster/project2064).
