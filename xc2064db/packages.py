"""Gehäuse des XC2064: Pin des Gehäuses -> Pad (benannt nach dem PLCC68-Pin wie die IOB-Bels, P2 ... P68).

Quelle: Xilinx Programmable Logic Data Book 1994, "XC2064 Configuration Pin Assignments" (S. 2-214), verglichen
mit dem von 1993 (S. 2-206). Nur die Pins mit Benutzer-I/O (die 58 Pads aus iob.js); Versorgung und
Konfiguration (GND, VCC, PWRDWN, RESET, DONE/PROG, CCLK, M0/RTRIG, M1/RDATA) haben kein IOB. M2, HDC, LDC,
RCLK, XTL1 und XTL2 sind nach der Konfiguration gewöhnliche I/O. Lieferformen laut Data Book 1993 (S. 2-208):

  PC68  68-Pin-PLCC, alle 58 Pads (Pin = Pad); -50, -70, -100
  PD48  48-Pin-DIL, 40 der 58 Pads; nur -50
  PC44  44-Pin-PLCC, 34 Pads; -70, -100
  PG68  68-Pin-PGA (Pins A2 ... L10 im 11x11-Raster), 57 Pads; -50, -70, -100

Abweichungen der beiden Data Books: PC44-Pin 20 liegt 1994 auf PLCC68-Pin 30, 1993 auf 31. 1994 stimmt mit dem
XC2018 überein, dessen PC44-Pin 20 wie PLCC68-Pin 30 des XC2064 der Konfigurationspin LDC ist (die Familie ist
im PC44 pinkompatibel); 1993 hat dort einen Druckfehler. Der PGA-Pin von PLCC68-Pin 65 heißt 1993 B8, 1994 D8
(kein Randpin, Druckfehler); hier B8. Für PLCC68-Pin 43 (XTL2 oder I/O) und 44 (RESET) nennen beide Bücher
keinen PGA-Pin; übrig sind K10 und L10, die Zuordnung ist offen. Pad P43 fehlt daher im PG68.
"""

# PD48: DIL-Pin -> PLCC68-Pin des Pads
PD48 = {
    1: 3, 2: 5, 3: 6, 4: 7, 5: 8, 6: 9, 8: 11, 9: 13, 10: 15, 11: 17, 13: 19, 14: 21, 15: 23, 16: 24, 19: 27,
    20: 28, 21: 30, 22: 32, 23: 34, 25: 37, 26: 39, 27: 40, 28: 41, 29: 42, 30: 43, 33: 46, 34: 48, 35: 50,
    36: 51, 37: 54, 38: 56, 39: 57, 40: 58, 41: 59, 43: 61, 44: 62, 45: 63, 46: 64, 47: 66, 48: 68,
}

# PC44: PLCC44-Pin -> PLCC68-Pin des Pads
PC44 = {
    2: 3, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 9: 11, 10: 12, 11: 13, 13: 19, 14: 20, 15: 21, 18: 27, 19: 28, 20: 30,
    21: 32, 22: 33, 24: 41, 25: 42, 26: 43, 29: 46, 30: 48, 31: 50, 32: 51, 34: 54, 35: 56, 36: 58, 37: 59,
    39: 61, 40: 62, 41: 63, 42: 64, 43: 66, 44: 68,
}

# PG68: PGA-Pin -> PLCC68-Pin des Pads
PG68 = {
    "A6": 2, "B5": 3, "A5": 4, "B4": 5, "A4": 6, "B3": 7, "A3": 8, "A2": 9, "B1": 11, "C2": 12, "C1": 13,
    "D2": 14, "D1": 15, "E2": 16, "E1": 17, "F1": 19, "G2": 20, "G1": 21, "H2": 22, "H1": 23, "J2": 24,
    "K2": 27, "L2": 28, "K3": 29, "L3": 30, "K4": 31, "L4": 32, "K5": 33, "L5": 34, "L6": 36, "K7": 37, "L7": 38,
    "K8": 39, "L8": 40, "K9": 41, "L9": 42, "J10": 46, "J11": 47, "H10": 48, "H11": 49, "G10": 50, "G11": 51,
    "F11": 53, "E10": 54, "E11": 55, "D10": 56, "D11": 57, "C10": 58, "C11": 59, "B10": 61, "A10": 62,
    "B9": 63, "A9": 64, "B8": 65, "A8": 66, "B7": 67, "A7": 68,
}

PACKAGES = ("PC68", "PD48", "PC44", "PG68")


def pads(package, all_pads):
    """{Pin-Name im Gehäuse: Pad} für PC68, PD48, PC44 bzw. PG68; all_pads: Namen der Pads (P2 ... P68)"""
    if package == "PC68":
        return {p: p for p in all_pads}
    if package in ("PD48", "PC44"):
        table = PD48 if package == "PD48" else PC44
        return {"P%d" % pin: "P%d" % plcc for pin, plcc in sorted(table.items())}
    if package == "PG68":
        return {pin: "P%d" % plcc for pin, plcc in sorted(PG68.items(), key=lambda kv: kv[1])}
    raise ValueError("unbekanntes Gehäuse %s (%s)" % (package, ", ".join(PACKAGES)))
