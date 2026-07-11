"""Adversarial CLI probes (Stage 5.5).

Pure-function checks on the output-spec parser, plus a few end-to-end subprocess
runs for argument errors and the (newly fixed) multi-config path.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hdldepends.api import select_top
from hdldepends.cli import _parse_output_kind
from hdldepends.model import FileType, Name, SourceFile
from hdldepends.resolver import Resolver

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --- output-spec parsing (pure) -------------------------------------------

def test_parse_output_kind_valid():
    assert _parse_output_kind("compile-order") == ("compile-order", None, None)
    assert _parse_output_kind("compile-order:lib=work") == ("compile-order", "lib", "work")
    assert _parse_output_kind("ext-list:tag=xdc") == ("ext-list", "tag", "xdc")


def test_parse_output_kind_unknown_kind():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_output_kind("not-a-kind")


def test_parse_output_kind_bad_selector_for_kind():
    # ext-list does not accept lib=
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_output_kind("ext-list:lib=work")
    # compile-order-json takes no selector
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_output_kind("compile-order-json:lib=work")


def test_parse_output_kind_selector_missing_equals():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_output_kind("compile-order:lib")


# --- Stage 6 F10 / api split: `select_top` (extracted from the 4 duplicated
# CLI-flag / config-fallback top-selection branches, now shared with the
# Python API's `analyze()`). These pin the exact error message TEXT the old
# inline code produced, so consolidating the branches cannot silently reword
# them. The explicit --top-file lookup itself (message "--top-file X is not
# in the project") lives inline in cli.py, not in `select_top` -- it's
# covered end to end by test_top_file_not_in_project_gives_clean_error_not_traceback
# below.

def test_select_top_prefers_explicit_top_file():
    r = Resolver()
    sf = SourceFile(Path("/x/a.vhd"), FileType.VHDL)
    r.add(sf)
    assert select_top(r, sf, Name("work", "irrelevant")) is sf


def test_select_top_config_top_file_missing_message_wording():
    # The config-fallback branch's wording ("config top file ...") must be
    # preserved distinctly from the --top-file branch's wording.
    r = Resolver()
    r.top_loc = Path("/x/missing.vhd")
    with pytest.raises(ValueError, match=r"config top file /x/missing\.vhd is not in the project"):
        select_top(r, None, None)


def test_select_top_by_name_found_returns_the_source_file():
    r = Resolver()
    sf = SourceFile(Path("/x/a.vhd"), FileType.VHDL, provides=[Name("work", "a")])
    r.add(sf)
    assert select_top(r, None, Name("work", "a")) is sf


def test_select_top_by_name_missing_raises_with_find_top_message():
    r = Resolver()
    with pytest.raises(ValueError, match="does_not_exist"):
        select_top(r, None, Name("work", "does_not_exist"))


def test_select_top_none_named_returns_none():
    r = Resolver()
    assert select_top(r, None, None) is None


# --- end-to-end subprocess -------------------------------------------------

def _run(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "hdldepends.hdldepends", *args]
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def _vhdl_basic(tmp_path) -> Path:
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES / "vhdl_basic", work)
    return work


def test_bad_output_kind_exits_with_argparse_error(tmp_path):
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "-o", "bogus", "out.txt"], work)
    assert r.returncode == 2  # argparse usage error


def test_compile_order_without_top_fails(tmp_path):
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "-o", "compile-order", "out.txt"], work)
    assert r.returncode != 0
    assert not (work / "out.txt").exists()


def test_top_entity_not_found_fails(tmp_path):
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "--top-entity", "does_not_exist", "-o", "compile-order", "out.txt"], work)
    assert r.returncode != 0


def test_top_entity_not_found_gives_clean_error_not_traceback(tmp_path):
    # E4: find_top raises KeyError; a typo in --top-entity previously escaped
    # cli.py as a raw traceback instead of a clean argparse-style error.
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "--top-entity", "does_not_exist", "-o", "compile-order", "out.txt"], work)
    assert r.returncode == 2  # argparse usage-error exit code, not an unhandled-exception exit
    assert "Traceback" not in r.stderr
    assert "does_not_exist" in r.stderr


def test_top_file_not_in_project_gives_clean_error_not_traceback(tmp_path):
    # Stage 6 F10 refactor safety net, end to end through the real CLI: a
    # --top-file naming a real file that just isn't part of THIS project
    # takes cli.py's inline by_loc-lookup path (as opposed to --top-entity's
    # `select_top` / find_top path, covered above).
    work = _vhdl_basic(tmp_path)
    (work / "not_in_project.vhd").write_text("library ieee;\nentity nip is end entity;\n")
    r = _run(["hdldeps.toml", "--top-file", "not_in_project.vhd", "-o", "compile-order", "out.txt"], work)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "not_in_project.vhd" in r.stderr
    assert "is not in the project" in r.stderr


def test_malformed_toml_config_gives_clean_error_not_traceback(tmp_path):
    # build_resolver was called with no exception handling at all in cli.py,
    # so even a config the loader itself has a well-typed error for (here, a
    # ConfigError wrapping the raw TOMLDecodeError) produced a raw traceback
    # via the CLI instead of the same clean, argparse-style error already
    # used for --top-entity / --top-file below.
    (tmp_path / "bad.toml").write_text("this is not valid toml @@@ [[[")
    r = _run(["bad.toml", "-o", "file-list", "out.txt"], tmp_path)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "bad.toml" in r.stderr


def test_config_error_gives_clean_error_not_traceback(tmp_path):
    # A ConfigError raised deep in build_resolver (here: min_ver too high)
    # previously propagated all the way out of cli.py as a raw traceback.
    (tmp_path / "highver.toml").write_text("min_ver = 999\nvhdl_files=[]\n")
    r = _run(["highver.toml", "-o", "file-list", "out.txt"], tmp_path)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "999" in r.stderr


def test_failing_pre_cmds_gives_clean_error_not_traceback(tmp_path):
    # A failing pre_cmds command raised subprocess.CalledProcessError, which
    # was neither wrapped in config.py nor in cli.py's caught set, so it
    # reached the user as a raw traceback.
    (tmp_path / "bad_precmd.yaml").write_text("pre_cmds: 'false'\nvhdl_files: []\n")
    r = _run(["bad_precmd.yaml", "-o", "file-list", "out.txt"], tmp_path)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "false" in r.stderr  # the failing command is named
    assert "bad_precmd.yaml" in r.stderr  # ...and so is the config file


def test_output_path_in_nonexistent_directory_gives_clean_error(tmp_path):
    # The FILE half of `-o KIND FILE` naming a directory that doesn't exist
    # previously raised a raw FileNotFoundError from output.py's open(loc, "w").
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "--top-entity", "del21", "-o", "compile-order", "no_such_dir/out.txt"], work)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "no_such_dir" in r.stderr
    assert not (work / "no_such_dir").exists()


def test_output_selector_bad_type_value_gives_clean_error(tmp_path):
    # `-o compile-order:type=BOGUS` previously raised a raw ValueError from
    # string_to_filetype deep inside _emit.
    work = _vhdl_basic(tmp_path)
    r = _run(["hdldeps.toml", "--top-entity", "del21", "-o", "compile-order:type=BOGUS", "out.txt"], work)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "BOGUS" in r.stderr


def test_duplicate_output_to_same_file_last_wins(tmp_path):
    work = _vhdl_basic(tmp_path)
    r = _run(
        ["hdldeps.toml", "--top-entity", "del21",
         "-o", "compile-order", "out.txt", "-o", "file-list", "out.txt"],
        work,
    )
    assert r.returncode == 0
    # second output (file-list) overwrote the first; file-list lines have no leading "VHDL"
    text = (work / "out.txt").read_text()
    assert "del21.vhd" in text


def test_glob_pattern_matching_directory_builds_cleanly_via_cli(tmp_path):
    # Stage 6 F6, end-to-end: a glob pattern that also matches a directory
    # (e.g. 'src/**' matching the 'src' dir itself) must not surface as a raw
    # IsADirectoryError traceback -- the directory is silently skipped and the
    # actual files still build normally.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "top.vhd").write_text("library ieee;\nentity top is end entity;\n")
    (tmp_path / "hdldeps.toml").write_text('vhdl_files_glob = ["src/**"]\n')
    r = _run(["hdldeps.toml", "--top-entity", "top", "-o", "compile-order", "out.txt"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    assert (tmp_path / "out.txt").exists()


def test_multiple_config_files_are_all_loaded(tmp_path):
    # Regression for the previously-broken multi-config path.
    (tmp_path / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (tmp_path / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    (tmp_path / "ca.toml").write_text("ignore_libs=['ieee']\nvhdl_files = { work = ['./a.vhd'] }\n")
    (tmp_path / "cb.toml").write_text("ignore_libs=['ieee']\nvhdl_files = { work = ['./b.vhd'] }\n")
    r = _run(["ca.toml", "cb.toml", "-o", "file-list", "fl.txt"], tmp_path)
    assert r.returncode == 0, r.stderr
    text = (tmp_path / "fl.txt").read_text()
    assert "a.vhd" in text and "b.vhd" in text


# --- python -m hdldepends (package __main__, distinct from the goldens'
# python -m hdldepends.hdldepends) -------------------------------------------

def test_python_dash_m_hdldepends_package_entry_point(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "hdldepends", "--version"], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert r.returncode == 0
    assert r.stdout.startswith("hdldepends ")
