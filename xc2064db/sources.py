# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sebastian Wittlich
"""Paths of the submodules (under external/) and reading their files. Paths are based on
os.path.realpath(__file__), so that the package is also found via the symlink in upstream/nextpnr. Line endings
(CRLF in Shirriff's files) are normalized."""
import hashlib
import os

ARCH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
EXTERNAL = os.path.join(ARCH, "external")
SHIRRIFF = os.path.join(EXTERNAL, "shirriff-xc2064")
OPENXC = os.path.join(EXTERNAL, "openxc2064")

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

# all bitstreams generated with XACT (cross-checks)
XACT_BITSTREAMS = [TEST1_RBT, OPENXC_AND_OR] + sorted(
    os.path.join(OPENXC_XACT_DIR, f) for f in (os.listdir(OPENXC_XACT_DIR) if os.path.isdir(OPENXC_XACT_DIR) else [])
    if f.upper().endswith(".BIT"))

# files from which the generator builds the chipdb (for the INPUTS in CMakeLists.txt)
GENERATOR_INPUTS = [DEF_TXT, DRAW_JS, CLB_JS, IOB_JS]


def read_text(path):
    """File as text with \\n as line ending. If it is missing, the submodule is usually missing."""
    if not os.path.exists(path):
        raise FileNotFoundError("%s is missing (git submodule update --init in arch/xc2064?)" % path)
    with open(path, "rb") as f:
        return f.read().decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def text_sha1(path):
    """SHA-1 of the text regardless of line endings (copies with and without CRLF count as equal)"""
    return hashlib.sha1(read_text(path).encode("latin-1")).hexdigest()
