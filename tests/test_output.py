"""Unit tests for the output writers (currently the compile-order JSON shape)."""

import builtins
import json
from pathlib import Path

from hdldepends.model import FileType, SourceFile
from hdldepends.output import write_compile_order, write_compile_order_json, write_ext_list, write_file_list


def test_json_separates_base_type_from_ver_tag(tmp_path, monkeypatch):
    # A @tag (e.g. VHDL2008) is reported as `ver_tag`; `type` stays the base
    # language (VHDL) so the two are independent. A file with no tag has no
    # `ver_tag` key at all.
    monkeypatch.chdir(tmp_path)
    tagged = SourceFile(Path("a.vhd"), FileType.VHDL, lib="mylib", ver="VHDL2008")
    plain = SourceFile(Path("b.vhd"), FileType.VHDL, lib="work")
    out = tmp_path / "order.json"
    write_compile_order_json([tagged, plain], {}, out)

    files = json.loads(out.read_text())["files"]
    assert files[0]["type"] == "VHDL"
    assert files[0]["ver_tag"] == "VHDL2008"
    assert files[0]["library"] == "mylib"
    assert files[1]["type"] == "VHDL"
    assert "ver_tag" not in files[1]
    assert files[1]["is_top"] is True  # last entry is the top


# --- write_ext_list must not print the literal string "None" ----------------

def test_write_ext_list_untagged_shows_empty_column_not_none(tmp_path):
    out = tmp_path / "ext.txt"
    write_ext_list({None: [Path("/x/a.xdc")], "tcl": [Path("/x/b.tcl")]}, out)

    text = out.read_text()
    lines = text.splitlines()
    assert "\t/x/a.xdc" in lines  # empty tag column, not "None\t..."
    assert "tcl\t/x/b.tcl" in lines
    assert "None" not in text


# --- the three plain-text writers must open with explicit utf-8 -------------

def test_output_writers_open_with_utf8_encoding(tmp_path, monkeypatch):
    calls = []
    real_open = builtins.open

    def spy_open(file, mode="r", *args, **kwargs):
        calls.append(kwargs.get("encoding"))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)

    write_compile_order([], tmp_path / "a.txt")
    write_file_list([], tmp_path / "b.txt")
    write_ext_list({}, tmp_path / "c.txt")

    assert calls == ["utf-8", "utf-8", "utf-8"]
