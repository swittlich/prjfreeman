"""XC2064 data from the submodules in external/, as the common basis for the chipdb generator
(names and connections) and the bitstream tools xc2064unpack/xc2064pack (bit map).

Sources (see README):
  shirriff-xc2064  Ken Shirriff's reverse engineering: XC2064-def.txt (all 11,360 bits), line names
                   (html/draw.js), CLB input muxes (html/clb.js), IOBs (html/iob.js)
  openxc2064       cross-check: switch matrix pattern, bitstreams generated with XACT

Modules:
  sources    paths and files of the submodules (CRLF-safe)
  bitmap     XC2064-def.txt: kind and name of every bit
  lines      line names and their G coordinates (draw.js), pips as the crossing of two lines
  switches   switch matrices: position, pins, connections (Magic bits)
  clbmux     CLB inputs A-D, K: sources and mux codes (clb.js)
  bitstream  reading .BIT and .RBT (frame <-> bit number)
"""
