"""Golden / characterization tests for hdldepends.

These tests lock in the *current* observable behaviour of the tool so that the
refactor (see the refactor plan) can proceed without silently changing output.

How it works
------------
Each :class:`Case` describes one invocation of the CLI against a self-contained
fixture project under ``tests/fixtures/<name>/``.  For every case we:

1. copy the fixture into a fresh temp working directory (so generated output
   files and any caches never pollute the repo),
2. run ``python -m hdldepends.hdldepends`` as a subprocess (faithful, isolated
   global state, deterministic hashing via ``PYTHONHASHSEED=0``),
3. capture exit code, stdout, stderr and the contents of every declared output
   file,
4. normalise environment-specific noise (the temp working directory path),
5. compare the result against a committed snapshot in ``tests/golden/<name>.snap``.

Updating goldens
----------------
After an *intentional* behaviour change, regenerate the snapshots with::

    HDLDEPENDS_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py

Review the resulting diff carefully before committing -- an unexpected change
there is exactly the regression these tests exist to catch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

UPDATE = os.environ.get("HDLDEPENDS_UPDATE_GOLDEN") == "1"


@dataclass
class Case:
    """One CLI invocation against a fixture project."""

    name: str
    #: extra CLI args appended after the config file.
    argv: List[str]
    #: output files (relative to the working dir) whose contents to snapshot.
    outputs: List[str] = field(default_factory=list)
    #: config file name inside the fixture dir.
    config: str = "hdldeps.toml"
    #: fixture directory under tests/fixtures/ (defaults to ``name``); set this
    #: when several cases drive the same fixture with different invocations.
    fixture: str = ""

    def __post_init__(self):
        if not self.fixture:
            self.fixture = self.name


# Each case targets a distinct code path. Outputs use the unified -o/--output
# interface; the deprecated flags get their own back-compat case below.
CASES: List[Case] = [
    # VHDL: parsing + entity resolution + topological compile order.
    Case(
        name="vhdl_basic",
        argv=["--top-entity", "del21", "-o", "compile-order", "compile_order.txt", "-o", "file-list", "file_list.txt"],
        outputs=["compile_order.txt", "file_list.txt"],
    ),
    # Verilog/SV: module/instantiation/include/package parsing.
    Case(
        name="verilog_basic",
        argv=["-o", "file-list", "file_list.txt"],
        outputs=["file_list.txt"],
    ),
    # Xilinx .xci (JSON) parsing + coefficient-file direct dependency.
    Case(
        name="xci_coef",
        argv=["-o", "file-list", "file_list.txt"],
        outputs=["file_list.txt"],
    ),
    # Xilinx .bd (block design) parsing.
    Case(
        name="bd_basic",
        argv=["-o", "file-list", "file_list.txt"],
        outputs=["file_list.txt"],
    ),
    # Xilinx tool-version handling: two same-named IPs (2022.2 vs 2024.2)
    # registered as a conflict, with the --x-tool-version filter code path
    # running. NOTE: in file-list mode both locations are still listed -- the
    # filter only prunes entity resolution during compile order, so this
    # snapshot documents that behaviour (see x_device_compile for filtering).
    Case(
        name="x_device_filter",
        argv=["--x-tool-version", "2024.2", "-o", "file-list", "file_list.txt"],
        outputs=["file_list.txt"],
    ),
    # YAML config (Phase 4): same project as vhdl_basic, proving YAML loads
    # end-to-end and produces the expected topological compile order.
    Case(
        name="yaml_basic",
        config="hdldeps.yaml",
        argv=["--top-entity", "del21", "-o", "compile-order", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # --- compile-order coverage ---
    # Verilog topological order: deps (module/package/include) before the top.
    Case(
        name="verilog_compile",
        fixture="verilog_basic",
        argv=["--top-entity", "up_down_counter", "-o", "compile-order", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # Xilinx .xci compile order: coefficient file ordered before the IP.
    Case(
        name="xci_compile",
        fixture="xci_coef",
        argv=["--top-entity", "fir_compiler_0", "-o", "compile-order", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # Xilinx .bd compile order over a complete block design: hdl + nested .bd
    # dependencies ordered before the top design.
    Case(
        name="bd_compile",
        argv=["--top-entity", "design_1", "-o", "compile-order", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # JSON compile order including external/coefficient emission (exercises the
    # XCI coefficient -> EXTERNAL path in write_compile_order_json).
    Case(
        name="xci_json",
        fixture="xci_coef",
        argv=["--top-entity", "fir_compiler_0", "-o", "compile-order-json", "compile_order.json"],
        outputs=["compile_order.json"],
    ),
    # Xilinx tool-version/device *selection* through compile order: two IPs with
    # the same entity name but different tool versions; filtering drops the
    # 2022.2 one so only the matching 2024.2 IP is in the order.
    Case(
        name="x_device_compile",
        fixture="x_device_filter",
        argv=[
            "--top-entity", "axi_bram_ctrl_0",
            "--x-tool-version", "2024.2",
            "--x-device", "xczu1cg-sbva484-2-e",
            "-o", "compile-order", "compile_order.txt",
        ],
        outputs=["compile_order.txt"],
    ),
    # Per-VHDL-library compile order via the -o selector syntax.
    Case(
        name="vhdl_lib_select",
        fixture="vhdl_basic",
        argv=["--top-entity", "del21", "-o", "compile-order:lib=work", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # Regression for the `end;` parser fix: led_controller_tb.vhd ends its entity
    # with `end;` (no space). Previously unparseable (the maintainer's own
    # test_led_controller_tb.sh failed); now it builds a correct compile order.
    Case(
        name="led_controller",
        argv=["--top-entity", "led_controller_tb", "-o", "compile-order:lib=work", "compile_order.txt"],
        outputs=["compile_order.txt"],
    ),
    # Config-driven top level (restored feature): `top_entity` is set in the
    # config file, not on the command line, so the compile order still needs a
    # top -- exercises the config top_*_file/top_entity -> resolver.top_loc /
    # resolver.top_name -> cli.py fallback path end to end.
    Case(
        name="config_top",
        argv=["-o", "compile-order", "compile_order.txt", "-o", "file-list", "file_list.txt"],
        outputs=["compile_order.txt", "file_list.txt"],
    ),
]


def _normalise(text: str, work_dir: Path) -> str:
    """Replace machine-specific paths with stable placeholders."""
    replacements = [str(work_dir), str(work_dir.resolve())]
    # also handle a possible /private prefix or trailing slash variants
    for needle in sorted(set(replacements), key=len, reverse=True):
        text = text.replace(needle, "<WORK>")
    return text


def _run_case(case: Case, tmp_path: Path) -> str:
    work = tmp_path / case.name
    shutil.copytree(FIXTURES_DIR / case.fixture, work)

    invocation = [case.config, *case.argv]
    cmd = [sys.executable, "-m", "hdldepends.hdldepends", *invocation]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONHASHSEED"] = "0"

    proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True)

    parts = [
        "$ hdldepends " + " ".join(invocation),
        f"exit: {proc.returncode}",
        "--- stdout ---",
        _normalise(proc.stdout, work).rstrip("\n"),
        "--- stderr ---",
        _normalise(proc.stderr, work).rstrip("\n"),
    ]
    for out in case.outputs:
        parts.append(f"--- file: {out} ---")
        out_path = work / out
        if out_path.exists():
            parts.append(_normalise(out_path.read_text(), work).rstrip("\n"))
        else:
            parts.append("<MISSING>")
    return "\n".join(parts) + "\n"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_golden(case: Case, tmp_path: Path) -> None:
    actual = _run_case(case, tmp_path)
    golden_file = GOLDEN_DIR / f"{case.name}.snap"

    if UPDATE:
        golden_file.parent.mkdir(parents=True, exist_ok=True)
        golden_file.write_text(actual)
        pytest.skip(f"updated golden: {golden_file.name}")

    assert golden_file.exists(), (
        f"missing golden {golden_file}; run with HDLDEPENDS_UPDATE_GOLDEN=1 to create it"
    )
    expected = golden_file.read_text()
    assert actual == expected, (
        f"output for case '{case.name}' changed.\n"
        f"If this change is intentional, regenerate with "
        f"HDLDEPENDS_UPDATE_GOLDEN=1 python -m pytest"
    )
