# VHDL-2008 + external files + exclusion example

A more involved project exercising several features together:

- **VHDL-2008 file type** — the whole `rtl/` tree is tagged `@VHDL2008`, so those
  files report type `VHDL2008` (vs a plain `VHDL`) in the compile order.
- **Glob + serial exclusion** — `rtl/**/*.vhd` pulls in everything, then
  `!rtl/_old/*.vhd` drops the stale `rtl/_old/legacy.vhd`, which never appears in
  the order.
- **Mixed language** — a SystemVerilog `clk_div` instantiated by the VHDL `core`.
- **External files** — `.xdc` constraints and `.tcl` scripts under `ext_files`
  (grouped by `@tag`); recorded for tooling but never compiled.

## Layout
```
hdldeps.yaml
rtl/pkg_types.vhd   package (VHDL2008, work)
rtl/alu.vhd         entity, uses work.pkg_types
rtl/clk_div.sv      SystemVerilog module (work)
rtl/core.vhd        instantiates work.clk_div + work.alu
rtl/top.vhd         top entity
rtl/_old/legacy.vhd EXCLUDED via `!rtl/_old/*.vhd`
constraints/pins.xdc   external (ext_files@xdc)
scripts/build.tcl      external (ext_files@tcl)
```

## Run
```sh
hdldepends hdldeps.yaml --top-entity top -o compile-order order.txt
```
Compile order (`<type> <library> <path>` — note `VHDL2008`, no `legacy`):
```
VERILOG  work rtl/clk_div.sv
VHDL2008 work rtl/pkg_types.vhd
VHDL2008 work rtl/alu.vhd
VHDL2008 work rtl/core.vhd
VHDL2008 work rtl/top.vhd
```
Extract the external files:
```sh
hdldepends hdldeps.yaml -o ext-list:tag=xdc xdc.txt      # constraints/pins.xdc
hdldepends hdldeps.yaml -o ext-list:tag=tcl tcl.txt      # scripts/build.tcl
hdldepends hdldeps.yaml -o ext-list all_external.txt     # both (tab-separated by tag)
```
