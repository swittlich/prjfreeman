# SPDX-License-Identifier: ISC
# Copyright (C) 2026 Sebastian Wittlich
# Prepare tristates for the formal comparison in run.sh (yosys JSON, flat, after "tribuf -logic"):
#   tristate_split.py <in.json> <out.json> <0|1>
# - Each tristate driver ($tribuf, $_TBUF_) becomes a multiplexer, "high-impedance" the constant 0 or 1.
#   If two netlists are equivalent with 0 and with 1, they are also equivalent with Z: if one drives where the
#   other is high-impedance, they differ in one of the two runs.
# - Each inout port P becomes an output, and whatever reads P reads the new input P$ext instead
#   (the value the outside world applies). That way the comparison also checks the read path.
# Keeps only the top module. Prints the number of tristate drivers and inout ports.
import json
import sys

src, dst, z = sys.argv[1], sys.argv[2], sys.argv[3]
design = json.load(open(src))
mods = design["modules"]
top_name = next(n for n, m in mods.items() if "top" in m.get("attributes", {}))
top = mods[top_name]
cells, ports = top["cells"], top["ports"]

n_tri = 0
for c in cells.values():
    con = c["connections"]
    if c["type"] == "$tribuf":
        c["type"] = "$mux"
        c["connections"] = {"A": [z] * len(con["A"]), "B": con["A"], "S": con["EN"], "Y": con["Y"]}
        c["port_directions"] = {"A": "input", "B": "input", "S": "input", "Y": "output"}
        c["parameters"] = {"WIDTH": c["parameters"]["WIDTH"]}
        n_tri += 1
    elif c["type"] == "$_TBUF_":
        c["type"] = "$_MUX_"
        c["connections"] = {"A": [z], "B": con["A"], "S": con["E"], "Y": con["Y"]}
        c["port_directions"] = {"A": "input", "B": "input", "S": "input", "Y": "output"}
        n_tri += 1

next_bit = 1 + max([b for p in ports.values() for b in p["bits"] if isinstance(b, int)]
                   + [b for c in cells.values() for s in c["connections"].values() for b in s if isinstance(b, int)]
                   + [b for n in top["netnames"].values() for b in n["bits"] if isinstance(b, int)] + [1])
n_inout = 0
for name in [n for n, p in ports.items() if p["direction"] == "inout"]:
    bits = ports[name]["bits"]
    ext = list(range(next_bit, next_bit + len(bits)))
    next_bit += len(bits)
    remap = {b: e for b, e in zip(bits, ext) if isinstance(b, int)}
    for c in cells.values():
        for p, sig in c["connections"].items():
            if c.get("port_directions", {}).get(p) == "input":
                c["connections"][p] = [remap.get(b, b) for b in sig]
    for other, p in ports.items():
        if other != name and p["direction"] == "output":
            p["bits"] = [remap.get(b, b) for b in p["bits"]]
    ports[name]["direction"] = "output"
    ports[name + "$ext"] = {"direction": "input", "bits": ext}
    top["netnames"][name + "$ext"] = {"hide_name": 0, "bits": ext, "attributes": {}}
    n_inout += 1

design["modules"] = {top_name: top}
json.dump(design, open(dst, "w"), indent=1)
print(n_tri + n_inout)
