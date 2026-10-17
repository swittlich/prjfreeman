"""Gehäuse des XC2064: Pin des Gehäuses -> Pad (benannt nach dem PLCC68-Pin wie die IOB-Bels, P2 ... P68).

Quelle: Xilinx Programmable Logic Data Book 1994, "XC2064 Configuration Pin Assignments" (S. 2-214). Nur die
Pins mit Benutzer-I/O (die 58 Pads aus iob.js); Versorgung und Konfiguration (GND, VCC, PWRDWN, RESET,
DONE/PROG, CCLK, M0/RTRIG, M1/RDATA) haben kein IOB. M2, HDC, LDC, RCLK, XTL1 und XTL2 sind nach der
Konfiguration gewöhnliche I/O.

  PC68  68-Pin-PLCC, alle 58 Pads (Pin = Pad)
  PD48  48-Pin-DIL (XC2064-50PD48, laut Lieferformen S. 2-216 nur als -50): 40 der 58 Pads
"""

# PD48: DIL-Pin -> PLCC68-Pin des Pads
PD48 = {
    1: 3, 2: 5, 3: 6, 4: 7, 5: 8, 6: 9, 8: 11, 9: 13, 10: 15, 11: 17, 13: 19, 14: 21, 15: 23, 16: 24, 19: 27,
    20: 28, 21: 30, 22: 32, 23: 34, 25: 37, 26: 39, 27: 40, 28: 41, 29: 42, 30: 43, 33: 46, 34: 48, 35: 50,
    36: 51, 37: 54, 38: 56, 39: 57, 40: 58, 41: 59, 43: 61, 44: 62, 45: 63, 46: 64, 47: 66, 48: 68,
}


def pads(package, all_pads):
    """{Pin-Name im Gehäuse: Pad} für PC68 bzw. PD48; all_pads: Namen der Pads (P2 ... P68)"""
    if package == "PC68":
        return {p: p for p in all_pads}
    if package == "PD48":
        return {"P%d" % dip: "P%d" % plcc for dip, plcc in sorted(PD48.items())}
    raise ValueError("unbekanntes Gehäuse %s (PC68 oder PD48)" % package)
