# hdldepends tests

## Golden / characterization tests (`test_golden.py`)

These lock in the **current observable behaviour** of the CLI so the in-progress
refactor can proceed without silently changing output. Each case runs the tool
against a self-contained fixture project in `fixtures/<name>/`, captures exit
code + stdout + stderr + declared output files (with machine-specific paths
normalised to `<WORK>`), and compares against the committed snapshot in
`golden/<name>.snap`.

### Run

The easiest way is the isolated-environment script, which creates a local
`.venv` (gitignored) so nothing touches your global / pyenv Python:

```sh
./scripts/setup_env.sh --test     # create .venv, install dev deps, run tests
# or, step by step:
./scripts/setup_env.sh            # create .venv + install
source .venv/bin/activate
python -m pytest
```

Use `./scripts/setup_env.sh --recreate` to rebuild the venv from scratch.

Without the script (installs into the current environment):

```sh
pip install -e '.[test]'      # or: pip install pytest
python -m pytest
```

### Update snapshots (after an *intentional* behaviour change)

```sh
HDLDEPENDS_UPDATE_GOLDEN=1 python -m pytest
```

Then review the diff under `tests/golden/` carefully before committing — an
unexpected change there is exactly the regression these tests exist to catch.

### Coverage notes

The fixtures are curated, hermetic mini-projects (no Vivado install or
environment variables required), built from the real source files under
`test/vhdl/`. They target distinct code paths:

| Case | Exercises | Output asserted |
|------|-----------|-----------------|
| `vhdl_basic` | VHDL parse, entity resolution, topological compile order | compile order + file list |
| `verilog_basic` | Verilog/SV module / instantiation / include / package parse | file list |
| `xci_coef` | Xilinx `.xci` (JSON) parse + coefficient direct-dependency | file list |
| `bd_basic` | Xilinx `.bd` block-design parse | file list |
| `x_device_filter` | two same-named IPs (conflict) + `--x-tool-version` filter path | file list |
| `verilog_compile` | Verilog topological compile order (deps before top) | compile order |
| `xci_compile` | `.xci` compile order (coefficient before IP) | compile order |
| `xci_json` | `--compile-order-json` incl. coefficient EXTERNAL emission | json output |
| `bd_compile` | complete `.bd` compile order (hdl + nested `.bd` before top) | compile order |
| `x_device_compile` | `--x-tool-version/--x-device` filtering through compile order | compile order |
| `yaml_basic` | YAML config loads end-to-end and orders correctly | compile order |

Beyond the golden cases there are unit tests: `test_parsers.py` (pure parsers),
`test_graph.py` (`compute_compile_order`), `test_vendor_xilinx.py` (Xilinx
file-object hooks), and `test_config.py` (the plain-Python config validation
gate, TOML/JSON/YAML load parity, and a drift guard that the schema's key set
matches the loader's `TOML_KEYS_*`).

A `Case` may set `fixture=` to drive an existing fixture directory with a
different invocation (e.g. `verilog_compile` reuses the `verilog_basic` fixture).

The verilog/xci/bd **compile-order** paths were fixed during Phase 2 coverage
widening (the verilog one needed a code fix; the Xilinx ones just needed
complete fixtures). The XML-format `.xci` parse path still has no fixture (all
`.xci` samples are JSON) and remains uncovered.
