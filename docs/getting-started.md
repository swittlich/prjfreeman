# Getting started

This repo is the `arch/xc2064` part of the repo that builds nextpnr and yosys (`scripts/build-nextpnr.sh`).
All paths in this documentation are relative to that repo's root. The data sources
[shirriff/xc2064](https://github.com/shirriff/xc2064) and [rates37/openxc2064](https://github.com/rates37/openxc2064)
are submodules under `external/`, at the commits listed in [Data sources](data-sources.md#submodules):

```bash
git clone --recurse-submodules https://github.com/swittlich/prjfreeman arch/xc2064   # fresh clone, with submodules
git -C arch/xc2064 submodule update --init                                            # already cloned: fetch the submodules
```

## Running the flow

```bash
scripts/build-nextpnr.sh debug              # after changes to nextpnr/* (incl. the generator)
arch/xc2064/flow.sh                         # synthesis + place & route with examples/blinky.pcf (5 MHz, FREQ=… changes it)
SEED=1 arch/xc2064/flow.sh                  # with a fixed nextpnr seed (without SEED: nextpnr default)
arch/xc2064/flow.sh arch/xc2064/examples/latch_sr.v   # a different design
arch/xc2064/flow.sh --gui                   # with the nextpnr GUI: Pack, Place, Route via the toolbar
arch/xc2064/test/run.sh                     # regression test (see testing.md)
arch/xc2064/test/bitstreams.sh              # check data sources, xc2064unpack, xc2064pack and Shirriff's decoder with XACT bitstreams
nextpnr-himbaechel --device XC2064 --json build/flows/xc2064/blinky.pnr.json --gui   # view the routed result
```

For the XC2064-50PD48, add `--device XC2064-50 --vopt package=PD48` and a PCF with the DIL pins;
likewise `--vopt package=PC44` (pins P2…P44) or `PG68` (pins like B5). How to go on from the routed
result to a bitstream is described in [Bitstream](bitstream.md).

nextpnr loads an already routed `*.pnr.json` directly in the GUI. On the command line it needs
`--no-pack`, since the result is already packed. A different speed grade is selected by the device name,
e.g. `--device XC2064-50` for the XC2064-PD48 (no suffix: -70).

Pins are constrained with a PCF file (`set_io <port> <pin>`); `flow.sh` picks up `design.pcf` next to
`design.v` automatically. Details, including how clocks are placed on the clock buffer pads, are in
[nextpnr uarch](nextpnr.md#pin-constraints-pcf-and-clock-placement). The example designs and their results
are listed in [Examples](examples.md).

## VS Code

In VS Code, the general tasks *Arch: Flow ausführen* (run flow) and *Arch: Flow mit nextpnr-GUI* (flow with
nextpnr GUI) work, as do the debug configurations for architectures (Run and Debug). Enter `xc2064` as the
name in each case.
