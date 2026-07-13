# hdldepends tests

## Golden / characterization tests (`test_golden.py`)

These lock in the **observable behaviour** of the CLI. Each case runs the tool
against a self-contained fixture project in `fixtures/<name>/`, captures exit
code + stdout + stderr + declared output files (with machine-specific paths
normalised to `<WORK>`), and compares against the committed snapshot in
`golden/<name>.snap`. A `Case` may set `fixture=` to drive an existing fixture
directory with a different invocation.

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
pip install -e '.[dev]'
python -m pytest
```

### Update snapshots (after an *intentional* behaviour change)

```sh
HDLDEPENDS_UPDATE_GOLDEN=1 python -m pytest
```

Then review the diff under `tests/golden/` carefully before committing — an
unexpected change there is exactly the regression these tests exist to catch.

## Other test modules

The fixtures are curated, hermetic mini-projects (no Vivado install or
environment variables required). Beyond the golden cases:

* `test_api.py` — the public Python API (`hdldepends.analyse()`), including
  parity with the `compile-order-json` writer.
* `test_sub_configs.py` — multi-`sub` config gathering completeness
  (regression suite for a historical "first sub silently skipped" bug).
* `test_parsers.py` — the pure VHDL/Verilog parsers.
* `test_resolver.py` — `Resolver` indexing, resolution and compile order.
* `test_output.py` — the output writers (compile-order JSON shape, ext lists).
* `test_config.py` / `test_config_features.py` — config validation gate,
  TOML/JSON/YAML load parity, `@tags`, globs, skip-order, ext files.
* `test_vendor_xilinx.py` — Xilinx `.bd`/`.xci` parsing and selection.
* `test_examples.py` — the committed `examples/` projects build end to end.
* `test_upstream_parity.py` — behaviours ported from the upstream project.
* `test_adversarial_*.py` — break-it probes (malformed configs, degenerate
  files, CLI misuse) pinning clean error handling.

The XML-format `.xci` parse path has no fixture (all `.xci` samples are JSON)
and remains uncovered.
