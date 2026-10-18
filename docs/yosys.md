# Synthesis (yosys plugin)

`yosys/synth_xc2064.cc` is built as a yosys plugin (`make -C arch/xc2064/yosys`, result
`yosys/build/xc2064.so`). Its script `synth_xc2064` produces exactly the primitives that the
[nextpnr uarch](nextpnr.md#primitives) expects:

```bash
yosys -m arch/xc2064/yosys/build/xc2064.so -p "synth_xc2064 -json out.json" design.v
```

Special features compared to a generic LUT flow:

- Tristate as with GateMate: after flattening, `tribuf -logic` turns internal tristate nets into logic,
  and `deminout` turns `inout` ports that are only read into inputs. `iopadmap` inserts `XC2000_TOBUF` or
  `XC2000_IOBUF` at ports with a tristate driver, and does so before LUT mapping. The inverter (enable in
  yosys, T = 1 turns the driver off) is then still absorbed into a LUT, and with an active-low enable it
  disappears entirely.
- State machines keep the encoding from the RTL (`synth -nofsm`): yosys would often re-encode them as
  one-hot, which is expensive on the XC2064 with one FF per CLB (`ampel.v`: 11 instead of 9 FFs), and the
  state register would no longer be named as in the RTL, which breaks the formal comparison in the
  regression test. `synth_xc2064 -fsm` enables re-encoding.
- `abc -lut 3:4` rates a LUT4 at the cost of two LUT3s.
- `dfflegalize` allows FF and latch with both clock polarities and asynchronous set/reset.
- The pass `xc2064_fgm` (after LUT mapping, can be disabled with `synth_xc2064 -nofgm`) merges the LUT in
  front of a storage element with the LUTs before it that feed only it, if the whole is a function of
  exactly 5 signals, including its own Q, and has the form `S ? f(a, c, x) : g(a, c, Q)` (or with F and G
  swapped). It then becomes an `XC2000_FGM`: S on B, a and c on inputs 1 and 2 of both tables, x or Q on
  input 3. With fewer signals a LUT4 suffices; without Q, FGM gains nothing. So far the pass only checks
  LUTs directly in front of the D LUT (one level)
- The pass `xc2064_iobff` (can be disabled with `-noiobff`) moves an FF into the IOB if its D is connected
  directly to an input, nothing else reads that input, and the FF switches on the rising edge without
  set/reset: `XC2000_INBUF` and `XC2000_DFF` become an `XC2000_INFF`. This saves one CLB per input.
  Inputs of `inout` ports (`XC2000_IOBUF`) stay direct
- The pass `xc2064_ffbuf` gives each FF its own driving LUT (or FGM).
- The custom cell types are not in yosys' `kernel/constids.inc`. `ID(...)` does not work for them with
  current yosys (Twine IdStrings); the pass creates them with `design->twines().add(...)`.
