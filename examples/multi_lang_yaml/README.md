# Multi-language + multi-library example (YAML config)

A small but realistic project that exercises most of `hdldepends`' features at once:

- **Two VHDL libraries** — `common_lib` (reusable) and `work` (the project).
- **Three languages** — VHDL, Verilog (`.v`) and SystemVerilog (`.sv`).
- **Cross-language instantiation** — the VHDL `datapath` instantiates the Verilog
  `sync_fifo` (which in turn instantiates the SystemVerilog `fifo`).
- **Cross-library instantiation** — `work.datapath` instantiates `common_lib.adder`.
- **YAML configuration**, including a **YAML sub-config** (`common_lib.yaml`).
- **Ignored libraries** (`ieee`, `std`) excluded from the compile order.

## Layout

```
hdldeps.yaml          top-level config (work sources + verilog + sub)
common_lib.yaml       sub-config: the reusable common_lib VHDL
common_lib/
  math_pkg.vhd        package  (common_lib)
  adder.vhd           entity   (common_lib, uses common_lib.math_pkg)
rtl/
  fifo.sv             SystemVerilog leaf module        (work)
  sync_fifo.v         Verilog, instantiates fifo        (work)
  datapath.vhd        VHDL, instantiates common_lib.adder + work.sync_fifo (work)
  top.vhd             VHDL top, instantiates work.datapath (work)
```

## Dependency graph

```
top (work)
└── datapath (work)
    ├── adder (common_lib) ── math_pkg (common_lib)
    └── sync_fifo (work, Verilog) ── fifo (work, SystemVerilog)
```

## Run it

```sh
hdldepends hdldeps.yaml --top-entity top -o compile-order order.txt
```

Produced compile order (dependencies first; `<type> <library> <path>`):

```
VHDL    common_lib  ./common_lib/math_pkg.vhd
VHDL    common_lib  ./common_lib/adder.vhd
VERILOG None        ./rtl/fifo.sv
VERILOG None        ./rtl/sync_fifo.v
VHDL    work        ./rtl/datapath.vhd
VHDL    work        ./rtl/top.vhd
```

Other handy invocations:

```sh
# Only the common_lib VHDL compile order (paths only):
hdldepends hdldeps.yaml --top-entity top -o compile-order:lib=common_lib common_lib.txt

# Every file in the project:
hdldepends hdldeps.yaml -o file-list files.txt
```
