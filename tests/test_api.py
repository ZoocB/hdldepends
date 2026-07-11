"""Tests for the public Python API (:mod:`hdldepends.api` / ``hdldepends.analyze``).

Fixture/config conventions mirror ``tests/test_golden.py`` (copy a project
under ``tests/fixtures/<name>/`` into a temp dir) and ``tests/test_config_features.py``
(build a minimal YAML config inline for cases no committed fixture covers).
"""

import json
import shutil
from pathlib import Path

import pytest

import hdldepends
from hdldepends import api
from hdldepends.config import build_resolver
from hdldepends.constants import LIB_DEFAULT
from hdldepends.errors import ConfigError
from hdldepends.model import Name
from hdldepends.output import write_compile_order_json

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _yaml(tmp_path, text, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content)
    (tmp_path / "hdldeps.yaml").write_text(text)


# --- parity with the compile-order-json writer ------------------------------

def test_analyze_matches_compile_order_json_file(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyze("hdldeps.toml", top_entity="del21")

    # Independently reproduce the compile-order-json file the CLI would write
    # for the same invocation, and check the API's dict-form output matches it
    # byte-for-byte (after JSON round-tripping).
    resolver = build_resolver("hdldeps.toml", work_dir=Path("."), top_lib=LIB_DEFAULT)
    top = resolver.find_top(Name(LIB_DEFAULT, "del21"))
    order = api.apply_forced_init_files(resolver, resolver.compile_order(top))
    json_path = work / "compile_order.json"
    write_compile_order_json(order, resolver.tag_2_ext, json_path)
    expected = json.loads(json_path.read_text())

    assert result.to_dict() == expected


def test_result_is_json_safe(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyze("hdldeps.toml", top_entity="del21")
    dumped = json.dumps(result.to_dict())
    assert json.loads(dumped) == result.to_dict()


def test_is_top_on_last_entry_only(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyze("hdldeps.toml", top_entity="del21")
    files = result.compile_order
    assert len(files) >= 2  # del21 depends on del211 -- more than just the top
    assert all("is_top" not in f for f in files[:-1])
    assert files[-1]["is_top"] is True
    assert files[-1]["path"].endswith("del21.vhd")


# --- EXTERNAL entries (tag_2_ext) --------------------------------------------

def test_ext_files_produce_leading_external_entries(tmp_path, monkeypatch):
    # No committed fixture uses ext_files; build a minimal one inline (same
    # pattern as test_config_features.py's ext_files test).
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\next_files:\n  - ./c.xdc\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        c__xdc="# constraints\n",
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("hdldeps.yaml")
    files = result.compile_order

    assert files[0]["type"] == "EXTERNAL"
    assert files[0]["file_ext"] == "XDC"
    assert files[0]["path"].endswith("c.xdc")
    assert files[-1]["is_top"] is True
    assert files[-1]["path"].endswith("top.vhd")


def test_ext_files_tagged_version_reported_as_ver_tag(tmp_path, monkeypatch):
    _yaml(
        tmp_path,
        "vhdl_files:\n  work:\n    - ./top.vhd\ntop_entity: top\next_files@constraints:\n  - ./c.xdc\n",
        top__vhd="library ieee;\nentity top is end entity;\n",
        c__xdc="# constraints\n",
    )
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("hdldeps.yaml")
    ext = result.compile_order[0]
    assert ext["type"] == "EXTERNAL"
    assert ext["ver_tag"] == "constraints"


# --- top-selection precedence ------------------------------------------------

def _two_entity_project(tmp_path):
    # `a` is both the config's top_entity AND (via top_vhdl_file) the config's
    # top file; `b` is a second, unrelated top-level entity so --top-entity /
    # top_file arguments can be pointed somewhere else and distinguished.
    (tmp_path / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (tmp_path / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    (tmp_path / "hdldeps.yaml").write_text(
        "vhdl_files:\n  work:\n    - ./a.vhd\n    - ./b.vhd\ntop_entity: a\n"
    )


def test_top_file_beats_top_entity_and_config_top(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("hdldeps.yaml", top_file="b.vhd", top_entity="a")
    assert result.compile_order[-1]["path"].endswith("b.vhd")


def test_top_entity_beats_config_top(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("hdldeps.yaml", top_entity="b")
    assert result.compile_order[-1]["path"].endswith("b.vhd")


def test_config_top_entity_used_when_nothing_explicit(tmp_path, monkeypatch):
    _two_entity_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = hdldepends.analyze("hdldeps.yaml")
    assert result.compile_order[-1]["path"].endswith("a.vhd")


def test_relative_top_file_is_anchored_to_work_dir(tmp_path, monkeypatch):
    # A relative top_file resolves against work_dir (like relative
    # config_files), NOT against the process CWD -- a library caller may not
    # control the CWD at all.
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = hdldepends.analyze("hdldeps.toml", work_dir=work, top_file="del21.vhd")
    assert result.compile_order[-1]["path"] == str(work / "del21.vhd")

    # Sanity check of the contrast: without work_dir the same relative
    # top_file is CWD-relative, which from `elsewhere` names no project file.
    with pytest.raises(ValueError, match="is not in the project"):
        hdldepends.analyze(str(work / "hdldeps.toml"), top_file="del21.vhd")


def test_absolute_top_file_ignores_work_dir(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = hdldepends.analyze("hdldeps.toml", work_dir=work, top_file=work / "del21.vhd")
    assert result.compile_order[-1]["path"] == str(work / "del21.vhd")


# --- errors -------------------------------------------------------------

def test_nonexistent_config_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises((ConfigError, OSError)):
        hdldepends.analyze("does_not_exist.yaml")


def test_top_entity_not_found_raises_value_error(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    with pytest.raises(ValueError):
        hdldepends.analyze("hdldeps.toml", top_entity="does_not_exist")


def test_top_file_not_in_project_raises_value_error(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    (work / "not_in_project.vhd").write_text("library ieee;\nentity nip is end entity;\n")
    monkeypatch.chdir(work)

    with pytest.raises(ValueError, match="not_in_project.vhd"):
        hdldepends.analyze("hdldeps.toml", top_file="not_in_project.vhd")


def test_no_top_anywhere_raises_value_error(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "verilog_basic", work)
    monkeypatch.chdir(work)

    with pytest.raises(ValueError):
        hdldepends.analyze("hdldeps.toml")


# --- config_files: single path vs sequence -----------------------------------

def test_config_files_accepts_single_path_or_str(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    by_str = hdldepends.analyze("hdldeps.toml", top_entity="del21")
    by_path = hdldepends.analyze(Path("hdldeps.toml"), top_entity="del21")
    assert by_str.to_dict() == by_path.to_dict()


def test_config_files_accepts_a_sequence(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    by_list = hdldepends.analyze(["hdldeps.toml"], top_entity="del21")
    by_str = hdldepends.analyze("hdldeps.toml", top_entity="del21")
    assert by_list.to_dict() == by_str.to_dict()


# --- x_tool_version / x_device kwargs ----------------------------------------

def test_x_tool_version_and_x_device_applied_to_resolver(tmp_path, monkeypatch):
    # x_device_filter registers two same-named Xilinx IPs (axi_a.xci /
    # axi_b.xci) at different tool versions/devices; only passing matching
    # x_tool_version + x_device selects axi_b.xci -- mirrors
    # tests/test_golden.py's x_device_compile CLI case (see that snapshot).
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "x_device_filter", work)
    monkeypatch.chdir(work)

    result = hdldepends.analyze(
        "hdldeps.toml",
        top_entity="axi_bram_ctrl_0",
        x_tool_version="2024.2",
        x_device="xczu1cg-sbva484-2-e",
    )
    assert [f["path"] for f in result.compile_order] == [str(work / "axi_b.xci")]


def test_x_tool_version_and_x_device_default_to_unset_on_resolver(tmp_path, monkeypatch):
    work = tmp_path / "proj"
    shutil.copytree(FIXTURES_DIR / "vhdl_basic", work)
    monkeypatch.chdir(work)

    resolver = build_resolver("hdldeps.toml", work_dir=Path("."), top_lib=LIB_DEFAULT)
    assert resolver.x_tool_version == ""
    assert resolver.x_device == ""
