"""Daten des XC2064 aus den Submodules in external/, als gemeinsame Grundlage für den Chipdb-Generator
(Namen und Verbindungen) und die Bitstream-Werkzeuge xc2064unpack/xc2064pack (Bitkarte).

Quellen (siehe README):
  shirriff-xc2064  Ken Shirriffs Reverse Engineering: XC2064-def.txt (alle 11.360 Bits), Leitungsnamen
                   (html/draw.js), CLB-Eingangs-Muxe (html/clb.js), IOBs (html/iob.js)
  openxc2064       Gegenprobe: Switch-Matrix-Muster, mit XACT erzeugte Bitstreams

Module:
  sources    Pfade und Dateien der Submodules (CRLF-fest)
  bitmap     XC2064-def.txt: Art und Name jedes Bits
  lines      Leitungsnamen und ihre G-Koordinaten (draw.js), Pips als Kreuzung zweier Leitungen
  switches   Switch-Matrizen: Lage, Pins, Verbindungen (Magic-Bits)
  clbmux     CLB-Eingänge A-D, K: Quellen und Mux-Codes (clb.js)
  bitstream  .BIT und .RBT lesen (Rahmen <-> Bitnummer)
"""
