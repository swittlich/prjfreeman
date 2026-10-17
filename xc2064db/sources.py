"""Pfade der Submodules und Lesen ihrer Dateien. Pfade hängen an os.path.realpath(__file__), damit das Paket
auch über den Symlink in upstream/nextpnr gefunden wird. Zeilenenden (CRLF in Shirriffs Dateien) werden
vereinheitlicht."""
import hashlib
import os

ARCH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SHIRRIFF = os.path.join(ARCH, "shirriff-xc2064")
OPENXC = os.path.join(ARCH, "openxc2064")

DEF_TXT = os.path.join(SHIRRIFF, "html", "XC2064-def.txt")
DRAW_JS = os.path.join(SHIRRIFF, "html", "draw.js")
CLB_JS = os.path.join(SHIRRIFF, "html", "clb.js")
IOB_JS = os.path.join(SHIRRIFF, "html", "iob.js")
TEST1_RBT = os.path.join(SHIRRIFF, "obsolete", "test", "TEST1.RBT")

OPENXC_DEF_TXT = os.path.join(OPENXC, "pin_planning", "XC2064-def.txt")
OPENXC_CSV = os.path.join(OPENXC, "bitstream", "XC2064-spreadsheet.csv")
OPENXC_GENERATOR = os.path.join(OPENXC, "bitstream", "generate_bitstream.py")
OPENXC_XACT_DIR = os.path.join(OPENXC, "bitstream", "XACT_comparisons")
OPENXC_AND_OR = os.path.join(OPENXC, "hardware", "bitstreams", "AND_OR.BIT")

# alle mit XACT erzeugten Bitstreams (Gegenproben)
XACT_BITSTREAMS = [TEST1_RBT, OPENXC_AND_OR] + sorted(
    os.path.join(OPENXC_XACT_DIR, f) for f in (os.listdir(OPENXC_XACT_DIR) if os.path.isdir(OPENXC_XACT_DIR) else [])
    if f.upper().endswith(".BIT"))

# Dateien, aus denen der Generator die Chipdb baut (für die INPUTS in CMakeLists.txt)
GENERATOR_INPUTS = [DEF_TXT, DRAW_JS, CLB_JS, IOB_JS]


def read_text(path):
    """Datei als Text mit \\n als Zeilenende. Fehlt sie, fehlt meist das Submodule."""
    if not os.path.exists(path):
        raise FileNotFoundError("%s fehlt (git submodule update --init in arch/xc2064?)" % path)
    with open(path, "rb") as f:
        return f.read().decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def text_sha1(path):
    """SHA-1 des Texts ohne Rücksicht auf Zeilenenden (Kopien mit und ohne CRLF gelten als gleich)"""
    return hashlib.sha1(read_text(path).encode("latin-1")).hexdigest()
