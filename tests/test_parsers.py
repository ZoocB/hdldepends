"""Unit tests for the pure parser functions (each returns a SourceFile)."""

from pathlib import Path

from hdldepends.parsers.verilog import parse_verilog_file
from hdldepends.parsers.vhdl import parse_vhdl_file
from hdldepends.vendors.xilinx.bd import parse_x_bd_file
from hdldepends.vendors.xilinx.xci import parse_x_xci_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _names(name_list):
    return {(n.lib, n.name) for n in name_list}


def test_parse_vhdl_provides_and_requires():
    f = parse_vhdl_file(FIXTURES / "vhdl_basic" / "del21.vhd", lib="work")
    assert ("work", "del21") in _names(f.provides)
    assert ("work", "del211") in _names(f.requires)
    leaf = parse_vhdl_file(FIXTURES / "vhdl_basic" / "del211.vhd", lib="work")
    assert ("work", "del211") in _names(leaf.provides)
    # only standard-library package uses (no work-library dependencies)
    assert {n for n in _names(leaf.requires) if n[0] not in ("ieee", "std")} == set()


def test_parse_vhdl_explicit_component_keyword_and_bare_use(tmp_path):
    # `: component foo` (explicit keyword) and `use lib.pkg;` (no trailing .all)
    f = tmp_path / "t.vhd"
    f.write_text(
        "library work;\n"
        "use work.my_pkg;\n"            # bare use, no `.all`
        "entity t is end entity;\n"
        "architecture a of t is begin\n"
        "  u0 : component foo port map (x => x);\n"   # explicit `component`
        "  u1 : bar port map (y => y);\n"             # plain component inst
        "end architecture;\n"
    )
    reqs = _names(parse_vhdl_file(f, lib="work").requires)
    assert ("work", "my_pkg") in reqs
    assert ("work", "foo") in reqs
    assert ("work", "bar") in reqs


def test_parse_vhdl_is_pure():
    a = parse_vhdl_file(FIXTURES / "vhdl_basic" / "del21.vhd", lib="work")
    b = parse_vhdl_file(FIXTURES / "vhdl_basic" / "del21.vhd", lib="work")
    assert a is not b
    assert _names(a.provides) == _names(b.provides)


def test_parse_verilog_modules_packages_instantiations():
    f = parse_verilog_file(FIXTURES / "verilog_basic" / "counter.v", None, [], [])
    assert ("work", "up_down_counter") in _names(f.provides)
    assert ("work", "axis_data_to_chdr") in _names(f.requires)
    assert ("work", "misc_package") in _names(f.requires)
    assert f.include_locs == []  # no include files passed in -> unresolved


def test_parse_xci_provides_and_coefficient_dep():
    f = parse_x_xci_file(FIXTURES / "xci_coef" / "fir_compiler_0.xci", None)
    assert ("work", "fir_compiler_0") in _names(f.provides)
    coe = [p for p in f.direct_deps if p.suffix == ".coe"]
    assert coe and coe[0].name == "fir_compiler_0_coefs.coe"


def test_parse_bd_provides_and_requires():
    f = parse_x_bd_file(FIXTURES / "bd_basic" / "design_1.bd", None)
    assert ("work", "design_1") in _names(f.provides)
    assert len(f.requires) > 0


# --- read_text_file_contents encoding fallback ------------------------------

def test_read_text_file_contents_falls_back_to_latin1_on_bad_utf8(tmp_path, capsys, monkeypatch):
    # \xe9 alone is not valid UTF-8 here (it's a 3-byte lead byte followed by a
    # plain space, not a continuation byte), but every single byte 0-255 is a
    # valid ISO-8859-1 character, so this must decode via the fallback rather
    # than crash.
    import hdldepends.logging_util as logging_util

    monkeypatch.setattr(logging_util, "log_level", 2)  # enable log.debug output

    p = tmp_path / "latin1.vhd"
    p.write_bytes(b"-- caf\xe9 comment\nentity foo is\nend entity;\n")
    f = parse_vhdl_file(p, lib="work")
    assert ("work", "foo") in _names(f.provides)

    err = capsys.readouterr().err
    assert "falling back to ISO-8859-1" in err
