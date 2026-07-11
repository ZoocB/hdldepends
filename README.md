# `hdldepends`
Simple python script to find HDL file dependencies.

# Install
```sh
git clone https://github.com/pevhall/hdldepends.git
cd hdldepends
pip install .
```
Requires Python >=3.8. Runtime dependency: `PyYAML` (YAML configs), plus
`tomli` on Python <3.10. Config validation is dependency-free plain Python.

# Development
Use the helper script to create an isolated virtual environment and run the
tests (nothing touches your global/pyenv Python):
```sh
./scripts/setup_env.sh --test
```
See [tests/README.md](tests/README.md) for the test layout (golden /
characterization tests plus per-stage unit tests).

# Usage

`hdldepends` reads one or more **configuration files** that describe your project
(which files belong to it and which libraries they live in), works out the
dependency-correct **compile order** starting from a top-level entity/file, and
writes that order out in whatever format your downstream tooling needs.

The general invocation is:

```sh
hdldepends <config-file...> [--top-entity NAME | --top-file PATH] -o KIND[:SELECTOR] OUTPUT_FILE
```

* **`<config-file...>`** — one or more config files (YAML/TOML/JSON). A bare name
  with no extension defaults to `.yaml`, and is searched for in parent directories.
* **top level** — set the root of the dependency walk with `--top-entity` (an
  entity/module name) or `--top-file` (a path already in the project), or with the
  equivalent config keys (`top_entity`, `top_vhdl_file`, …).
* **`-o`** — choose an output kind and destination file; repeatable (see
  [Command line](#-o---output)).

A typical run:

```sh
# resolve the compile order for entity `top` and write it three ways
hdldepends hdldepends.yaml --top-entity top \
  -o compile-order order.txt \
  -o compile-order-json order.json \
  -o ext-list:tag=xdc constraints.txt
```

Run `hdldepends -h` for the full flag list, or see the sections below.

# Basic VHDL Example
Create a YAML config in the root of your project listing the library VHDL files
(globs are allowed):

```yaml
# hdldepends.yaml
vhdl_files:
  work:
    - 'fw/lib/vhdl/**/*.vhd'
```

Now from a sub directory dump the VHDL `work` library compile order for a top level testbench:
```
hdldepends hdldepends.yaml --top-file ../vhdl/example_tb.vhd -o compile-order:lib=work compile_order.txt
```

There is a fuller, multi-language example under
[examples/multi_lang_yaml/](examples/multi_lang_yaml/).

# Configuration file Keys/Options
A config holds the project information: which files are included and which
libraries they belong to. **YAML is the primary format** (`.yaml` / `.yml`); TOML
and JSON still load. A bare config name with no extension defaults to `.yaml`.
The file is a set of key/value pairs (the keys below); it is validated against a
schema, so unknown keys and malformed values are reported with a clear error.

## Complete YAML configuration reference

The following single file exercises every supported key. You will rarely need all
of them at once — treat it as a menu. Each key is explained in detail in the
sections below.

```yaml
# hdldepends.yaml — annotated reference (YAML is the primary format)

# --- minimum tool version (optional) --------------------------------------
min_ver: 1.0                       # error out if hdldepends is older than this

# --- commands to run first (optional) -------------------------------------
pre_cmds:                          # run before any files are gathered
  - 'git ls-files ./fw | grep "\.vhd$" > fw_files.txt'

# --- source files ---------------------------------------------------------
# Every entry is a glob pattern; a leading '!' removes earlier matches.
# VHDL keys take a per-library mapping (the key is the library name);
# all other languages are single, flat lists (library is always `work`).

vhdl_files:                        # VHDL, grouped by library
  common_lib:
    - 'fw/lib/**/*.vhd'
  work:
    - 'rtl/**/*.vhd'
    - '!rtl/_old/*.vhd'            # drop deprecated files included above

vhdl_files@VHDL2008:               # @tag separates VHDL2008 from VHDL93 (shown
  work:                            # as the file "type" and in the output)
    - 'rtl/new/*.vhd'

vhdl_files_file:                   # read patterns from a text file (one per line)
  work: './fw_files.txt'

verilog_files:                     # Verilog / SystemVerilog (no libraries)
  - 'rtl/**/*.sv'
  - 'rtl/**/*.v'
verilog_include_dir:               # search dirs for `include` headers
  - 'rtl/include'
verilog_include_files:             # explicit header files
  - 'rtl/include/defs.vh'

x_xci_files:                       # Xilinx LogiCORE IP (.xci), scanned for deps
  - 'ip/**/*.xci'
x_bd_files:                        # Xilinx block designs (.bd)
  - 'bd/**/*.bd'

other_files:                       # not scanned; stem = module name; IN the order
  - 'ip/legacy/*.edf'

ext_files@xdc:                     # external, never compiled (constraints/scripts)
  - 'constraints/*.xdc'
ext_files@tcl:
  - 'scripts/*.tcl'

# --- forced add (encrypted / unparseable HDL) -----------------------------
init_files:                        # [path, type, version_tag?, library?, name?]
  - ['./ip/secret_ip.edn', 'VHDL', '', 'work', 'secret_ip']

# --- top level (optional; can also be set on the command line) ------------
top_entity: top                    # entity/module to start the walk from
# top_vhdl_file: rtl/top.vhd       # ...or point at a specific file instead

# --- Xilinx selection (optional; CLI flags override) ----------------------
x_tool_version: '2022.2'           # pick among .xci/.bd variants by Vivado version
x_device: 'xc7z020clg400-1'        # ...and/or by device

# --- things to ignore -----------------------------------------------------
ignore_libs: [ieee, std]           # libraries never added to the order
ignore_packages:                   # VHDL packages to skip (per-library)
  work: [debug_pkg]
ignore_entities:
  work: [sim_only_ent]
ignore_components: [chipscope]     # components to skip (library not specified)

vhdl_package_skip_order:           # parse (so names resolve) but keep OUT of order
  unisim: '{XILINX_VIVADO}/data/vhdl/src/unisims/unisim_VCOMP.vhd'

# --- compose multiple configs ---------------------------------------------
sub:                               # pull in other config files
  - './fw/lib/common_lib.yaml'
```

## Source File options

There are a number of ways to add different source files to the "project". Source File keys/options are made up of the following first:
 * language first, then
 * an input type, and finally
 * an optional custom tag
They are combined as follows {language}_{input_type}@{custom_tag}

All current possible {language}_{input_type} options are:
 * `vhdl_files`
 * `vhdl_files_file`
 * `vhdl_files_glob`
 * `verilog_files`
 * `verilog_files_file`
 * `verilog_files_glob`
 * `verilog_include_dir`
 * `verilog_include_files`
 * `verilog_include_files_file`
 * `verilog_include_files_glob`
 * `x_xci_files`
 * `x_xci_files_file`
 * `x_xci_files_glob`
 * `x_bd_files`
 * `x_bd_files_file`
 * `x_bd_files_glob`
 * `other_files`
 * `other_files_file`
 * `other_files_glob`
 * `ext_files`
 * `ext_files_file`
 * `ext_files_glob`


### Custom Tag
At the end of a configuration file key/option a custom file tag can be added. The custom tag can be used to separate different sets of the same file type. The custom tag will be exported with the --compile-order.

The custom tags to distinguish the difference between VHDL93 and VHDL2008. This was required because currently Vivado can only add VHDL93 files (and not VHDL2008) to block diagrams.

### Input types
Each source key comes in three input forms (all relative to the config file's
directory, or absolute):

* `*_files` — a list of patterns (this is the usual one).
* `*_files_glob` — an alias for `*_files`; they behave identically.
* `*_files_file` — a path to a text file that itself lists patterns (one per line).

**Every entry is a glob pattern**, so you can freely mix plain paths and globs in
the same list — you do not need a separate `_glob` key:

* `*` matches anything within a directory
* `**` matches directories recursively
* a leading `!` *removes* earlier matches

Patterns are applied **serially**, so order matters: a `!` pattern only removes
files that were included by an earlier pattern. For example:

```yaml
vhdl_files:
  work:
    - 'src/**/*.vhd'   # include all VHDL under src/
    - '!src/tb/*.vhd'  # then drop the testbenches
    - 'extra/special.vhd'
```

A plain path is just a glob that matches itself, so `./top.vhd` and `'src/*.vhd'`
can sit in the same list.

### Languages
Supported languages are

* `vhdl_*`
* `verilog_*`
* `x_xci_*`
* `x_bd_*`
* `other_*`
* `ext_*`

#### `vhdl_*`
VHDL is the only language where libraries are supported.

So for the VHDL options instead of just having a list the `vhdl_files`, `vhdl_files_file` and `vhdl_files_glob` support directories where the key is the library to add the VHDL files into. This can also be a directories to a list if you want to add multiple elements to the same directory. If the library is not specified then the default library is used.

#### `verilog_*`
Verilog/SystemVerilog files do not support libraries (everything is `work`).

Header (`include) files are resolved via two extra keys:

* `verilog_include_dir` — directories to search for `include`d headers (a list or
  single path).
* `verilog_include_files` / `_file` / `_glob` — explicit header files to register
  so an `include "foo.vh"` can resolve to them.

These headers are read to resolve includes but are not themselves placed in the
compile order.

#### `x_xci_*`
Xilinx LogiCORE IP (XCI) files are currently scanned for VHDL, Verilog and or nested BD dependencies.

The Vivado version and Xilinx part number will be extracted from the file. If multiple files with the same entity are found the program will try to filter out the correct version using the command line options --x-tool-version and --x-device.

Note: this is currently only tested on Vivado 2022.2

#### `x_bd_*`
Xilinx Block Diagrams (BD) files are currently scanned for VHDL, Verilog and or nested BD dependencies.

The Vivado version and Xilinx part number will be extracted from the file. If multiple files with the same entity are found the program will try to filter out the correct version using the command line options --x-tool-version and --x-device.

Note: XCI inside the BD can be regenerated by the BD and so are not a dependency of the BD.

Note: this is currently only tested on Vivado 2022.2

#### `other_*` vs `ext_*` — files that are not HDL

`other_*` files are *not* scanned; the file name minus its extension is taken as
the module name and the file **is** placed in the compile order (originally used
for XCI files before `x_xci_*` existed).

`ext_*` ("external") files are also not scanned but are **never** part of the
compile order — they are project files such as Vivado constraints (`.xdc`) or
build scripts (`.tcl`) that the build needs but that have no compile dependency.
hdldepends just records where they are; extract them with:

```sh
hdldepends proj.yaml -o ext-list constraints_and_scripts.txt   # all external files
hdldepends proj.yaml -o ext-list:tag=xdc xdc_files.txt          # only the @xdc tag
```

The `@tag` on an `ext_files` key groups them (e.g. `ext_files@xdc` vs
`ext_files@tcl`).

#### `vhdl_package_skip_order`
Lists VHDL files — typically Xilinx primitive packages such as `unisim` — that
must be **parsed** so the packages/entities they declare can be discovered, but
that must be kept **out** of the compile order (the tool/simulator already
provides them). Paths may use `{ENV_VAR}` (e.g. `{XILINX_VIVADO}/...`):

```yaml
vhdl_package_skip_order:
  unisim: '{XILINX_VIVADO}/data/vhdl/src/unisims/unisim_VCOMP.vhd'
```

## Top level file
If you want to generate the compile order you will need to have the top level file set. This can be set in the configuration file using one of these options or set in the command line options.

Note: A configuration containing a top file setting cannot be reference by another configuration through the `sub` option.

### `top_vhdl_file`
Set the passed VHDL file as the top level file

### `top_verilog_file`
Set the passed Verilog file as the top level file

### `top_x_bd_file`
Set the passed Xilinx BD file as the top level file

### `top_entity`
This is the top entity to create the compile order from. This entity must be included in the file options.

## Files to ignore
This options are about telling the compile order processing to ignore things.

For options that accept a *library* dictionary, then the dictionary key is the library name. The dictionary value can be a list to contain more then one item to connect to the library. If no dictionary is not specified then the default `work` library is assumed.

### `ignore_libs`
Ignore libraries key indicates libraries which the design will ignore not add to the compile order.

This option accepts a list or single value.

### `ignore_packages`
Ignore packages key indicates VHDL packages which the design will ignore not add to the compile order.

This option accepts a *library* dictionary list or single value.

### `ignore_entities`
Ignore entities key indicates entities which the design will ignore not add to the compile order.

This ken accepts a *library* dictionary list or single value.

### `ignore_components`
Ignore components key indicates components which the design will ignore not add to the compile order.

NOTE: you do not indicate which library the component comes from.

This key accepts a list or single value.

### `vhdl_package_skip_order`
Package file skip order key added the package to the project but will ignore the package and all components in the package when creating the compile order. 

This key accepts a *library* dictionary list or single value.

### `init_files` (forced add)
Forced-add files that hdldepends should **not** parse but must still be known to the
resolver and force-included in the compile order. The classic case is an *encrypted /
binary* netlist (e.g. an `.edn` or pre-compiled IP) that has an entity name another file
instantiates: hdldepends cannot read it, so without this the instantiation would fail to
resolve. Each entry is a list `[path, type, version_tag?, library?, name?]`:

```yaml
init_files:
  # secret_ip.edn provides entity `secret_ip` in library `work`; never parsed,
  # but instantiations of work.secret_ip now resolve and it lands in the order.
  - ['./ip/secret_ip.edn', 'VHDL', '', 'work', 'secret_ip']
```

If `name` is omitted the file stem is used as the provided name. A forced file that nothing
instantiates is still prepended to the compile order. (Forced *ignores* are the inverse —
see `ignore_entities`, `ignore_components`, `ignore_packages`, `ignore_libs` and
`vhdl_package_skip_order` above.)

## Other options
Other options

### `pre_cmds`
Pre-commands are commands to run before other keys are processed.

This key accepts a list or a single value.

The major purpose of this is to automatically update files referenced by a `*_files_file` key (e.g. `vhdl_files_file`). An example of `pre_cmds` could be.
```
git ls_files ./fw | grep ".vhd$" > fw_files_work.txt
```
This will place all `.vhd` files paths into fw-files_work.txt.

### `sub`
The sub key adds other configuration files to the project. Which will be searched after the current configuration file. This can be a path relative to the directory containing this file or a file name contained in a parent directory of this file.

This key accepts a list or a single value.

### `x_tool_version` / `x_device`
Select which Xilinx `.xci`/`.bd` variant to use when several share an entity name,
by Vivado tool version and/or device. These are the config-file equivalents of the
`--x-tool-version` / `--x-device` command line flags (the flags take priority).

Each accepts a single value.

### `min_ver`
Require a minimum `hdldepends` version; the tool errors out if it is older. Accepts
a number.

# Command line
Below are the command line options for the `hdldepnds.py` command line program

## Options
Command line flag options

### `-h` `--help`
Print help message and exit

### `--version`
Print the `hdldepends` version and exit.

### `-v` `--verbose`
Selected the verbose level. 
 * Nothing is *warning*
 * `-v` is *info*, and
 * `-vv` is *debug*.


### `--top-file`
The top file command line option specifies the project's top level file to create the compile order from. This works the same as the configuration file keys `top_vhdl_file` / `top_verilog_file` / `top_x_bd_file`.

### `--top-entity`
The top file command line option specifies the project's top level file to create the compile order from. This works the same as the configuration file key `top_entity`.

### `--top-vhdl-lib`
This is a bit of a hack. It will give the `work` library the passed name.

### `-o` `--output`
All outputs are produced with a single, repeatable option:

```
-o KIND[:SELECTOR] FILE
```

`KIND` is one of:
 * `compile-order` — project compile order; each line is *file type, library, path*.
 * `compile-order-paths` — compile order, paths only.
 * `compile-order-json` — complete compile order as JSON (incl. external/coefficient files).
 * `file-list` — every file in the project (lines: *library, path*).
 * `ext-list` — external files only (those not scanned / not in the compile order).

`SELECTOR` is optional and narrows the output:
 * `:lib=LIB` — restrict to one VHDL library (`compile-order`, `file-list`).
 * `:type=TYPE` — restrict to one file type: `vhdl`, `verilog`, `x_bd`, `other` (`compile-order`, `file-list`).
 * `:tag=TAG` — restrict to one custom tag (`ext-list`).

`-o` may be given multiple times. Examples:

```
hdldepends proj.toml --top-entity top -o compile-order order.txt
hdldepends proj.toml --top-entity top -o compile-order:lib=work work_order.txt -o file-list files.txt
hdldepends proj.toml --top-entity top -o compile-order-json proj.json
hdldepends proj.toml -o ext-list:tag=xdc constraints.txt
```

### `--x-tool-version`
This option specifies the Vivado version, it is used when passing the Xilinx XCI and BD files. It will try and get the correct tool version.

### `--x-device`
This option specifies the Xilinx device is used when passing the Xilinx XCI and BD files. It will try and get the Xilinx device.

Note `--x-tool-version` will take priority over `--x-device` so if it can only match one it will match the tool version.

## Positional Arguments
This program has only one positional argument type.

### `config_file`
This can be a direct path to a configuration file or just the file name. If only the file name is specified the program will look in parent directories for the file.

More then one configuration file can be specified. If more then one file is specified use the `--top-vhdl-lib` command line option and not a `top_vhdl_file` / `top_verilog_file` / `top_x_bd_file` configuration file key.

## Paths
File paths can be relative to the file that contains the paths or relative to the current directory if passed by the command line.

# Architecture
`hdldepends` is a small package built around one idea: parse every file into a
uniform record of what it *provides* and *requires*, index those records by
name, then walk the index from a top file to get the compile order.

| Module | Responsibility |
|--------|----------------|
| `constants`, `logging_util`, `util`, `discovery` | leaf helpers (constants, logging, path/IO utilities, glob discovery) |
| `model` | `Name`, `FileType`, and the single `SourceFile` record (`provides` / `requires` / `direct_deps`) |
| `parsers/vhdl`, `parsers/verilog` | pure parsers: a file in → a `SourceFile` out |
| `vendors/xilinx/` | `.xci` / `.bd` parsers (also return `SourceFile`, with device/tool-version metadata) |
| `resolver` | the flat name→file index and the depth-first `compile_order` walk |
| `config`, `config_models` | load + validate config (TOML/JSON/YAML), discover files, build the `Resolver` |
| `output` | write the compile order / file lists / JSON |
| `cli` | argument parsing and the console-script entry point |
| `hdldepends` | facade that re-exports the public surface |

The whole dependency walk lives in `Resolver.compile_order`: visit a file,
recurse into the files providing each name it requires, and append it after its
dependencies. There is no lookup tree and no per-file-type resolution policy —
sub-configs and libraries all populate one flat index. Xilinx device/tool-version
selection is the one extra rule, applied in `Resolver.resolve`.
