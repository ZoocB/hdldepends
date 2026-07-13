"""Xilinx vendor-parser unit tests (parsers return SourceFile)."""

import json
from pathlib import Path

import pytest

from hdldepends.model import FileType, Name, SourceFile
from hdldepends.resolver import Resolver, _closest_x_version, _select_x, _version_key
from hdldepends.vendors.xilinx.bd import parse_x_bd_file
from hdldepends.vendors.xilinx.xci import parse_x_xci_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# --- minimal, valid-shaped XCI XML fixture builder (no XML fixture file exists
# in tests/fixtures -- the real-world fixtures are all JSON-format .xci) --------

_XCI_XML_NS = (
    'xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009" '
    'xmlns:xilinx="http://www.xilinx.com"'
)

_XCI_XML_DEFAULT_PARAMS = {
    "PROJECT_PARAM.DEVICE": "xc7a35t",
    "PROJECT_PARAM.PACKAGE": "cpg236",
    "PROJECT_PARAM.SPEEDGRADE": "-1",
    "PROJECT_PARAM.TEMPERATURE_GRADE": "i",
    "RUNTIME_PARAM.SWVERSION": "2020.1",
}


def _xci_xml(overrides=None, omit=(), extra_elements="", instance_name="my_ip_0", omit_library=False):
    """Build a minimal, valid-shaped XCI XML document for tests.

    ``overrides`` replaces individual PROJECT_PARAM/RUNTIME_PARAM values (an
    empty string renders as ``<tag></tag>``, i.e. ``elem.text is None``).
    ``omit`` drops keys (and their element) entirely. ``extra_elements`` is raw
    XML appended after the standard params (e.g. coefficient-file elements).
    """
    params = dict(_XCI_XML_DEFAULT_PARAMS)
    if overrides:
        params.update(overrides)
    for key in omit:
        params.pop(key, None)
    lines = "\n".join(
        f'    <spirit:configurableElementValue spirit:referenceId="{k}">{v}</spirit:configurableElementValue>'
        for k, v in params.items()
    )
    library_elem = "<spirit:library/>" if omit_library else "<spirit:library>xci</spirit:library>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<spirit:design {_XCI_XML_NS}>
  {library_elem}
  <spirit:instanceName>{instance_name}</spirit:instanceName>
  <spirit:configurableElementValues>
{lines}
{extra_elements}
  </spirit:configurableElementValues>
</spirit:design>
"""


def _two_versions():
    """Both fixtures provide axi_bram_ctrl_0 on the same device; only the Vivado
    tool version differs (axi_a 2022.2, axi_b 2024.2)."""
    return (
        parse_x_xci_file(FIXTURES / "x_device_filter" / "axi_a.xci", None),  # 2022.2
        parse_x_xci_file(FIXTURES / "x_device_filter" / "axi_b.xci", None),  # 2024.2
    )


def test_xci_is_x_with_device_metadata():
    sf = parse_x_xci_file(FIXTURES / "x_device_filter" / "axi_b.xci", None)
    assert sf.is_x and sf.ftype == FileType.X_XCI
    assert sf.x_tool_version == "2024.2" and sf.x_device


def test_x_selection_picks_exact_tool_version():
    # Two same-named IPs (different tool versions); the resolver selects by --x-*.
    a, b = _two_versions()
    r = Resolver()
    r.add(a)
    r.add(b)
    r.x_tool_version = "2024.2"
    r.x_device = "xczu1cg-sbva484-2-e"
    chosen = r.resolve(Name("work", "axi_bram_ctrl_0"))
    assert chosen is not None and chosen.loc.name == "axi_b.xci"


def test_select_x_priority_exact_then_version_then_device():
    a, b = _two_versions()  # both device xczu1cg-sbva484-2-e
    dev = a.x_device
    # exact version+device wins
    assert _select_x([a, b], "2022.2", dev) is a
    assert _select_x([a, b], "2024.2", dev) is b
    # device matches but version does not -> closest version (prefer highest <= target)
    assert _select_x([a, b], "2023.1", dev) is a   # 2022.2 is highest at/below 2023.1
    assert _select_x([a, b], "2025.1", dev) is b   # 2024.2 is highest at/below 2025.1
    assert _select_x([a, b], "2020.1", dev) is a   # none below -> lowest above


def test_closest_x_version_prefers_lower_upgradeable():
    a, b = _two_versions()
    assert _closest_x_version([a, b], "2023.1") is a   # highest at/below target
    assert _closest_x_version([a, b], "2024.2") is b   # exact at/below
    assert _closest_x_version([a, b], "2019.1") is a   # all above -> lowest


def test_xci_inherits_library_from_vhdl_parent(tmp_path):
    # An XCI starts in the default 'work' library but adopts the library of the
    # VHDL file that instantiates it, so a netlist generated from it is valid.
    _, xci = _two_versions()
    assert xci.lib == "work"
    r = Resolver()
    r.add(xci)
    top = SourceFile(tmp_path / "top.vhd", FileType.VHDL, lib="mylib")
    top.provides.append(Name("mylib", "top"))
    top.requires.append(Name("mylib", "axi_bram_ctrl_0"))
    r.add(top)

    r.compile_order(r.find_top(Name("mylib", "top")))
    assert xci.lib == "mylib"
    assert xci.lib_inherited_from == top.loc


def test_xci_library_inheritance_first_parent_wins(tmp_path):
    # A second, differently-libraried parent does not override the first.
    _, xci = _two_versions()
    r = Resolver()
    r.add(xci)
    for lib in ("lib_a", "lib_b"):
        p = SourceFile(tmp_path / f"{lib}_top.vhd", FileType.VHDL, lib=lib)
        p.provides.append(Name(lib, f"{lib}_top"))
        p.requires.append(Name(lib, "axi_bram_ctrl_0"))
        r.add(p)
        r.compile_order(r.find_top(Name(lib, f"{lib}_top")))
    assert xci.lib == "lib_a"  # first parent walked wins


def test_malformed_or_empty_xci_raises(tmp_path):
    # Neither sub-parser can make sense of empty content, so parse_x_xci_file
    # falls through to its own final RuntimeError (see also
    # test_adversarial_vendor.test_empty_xci_raises).
    (tmp_path / "empty.xci").write_text("")
    with pytest.raises(RuntimeError):
        parse_x_xci_file(tmp_path / "empty.xci", None)


def test_bd_missing_design_key_raises(tmp_path):
    # Malformed .bd raises a RuntimeError naming the file, not a bare KeyError.
    (tmp_path / "nodesign.bd").write_text('{"something_else": {}}')
    with pytest.raises(RuntimeError, match="nodesign.bd"):
        parse_x_bd_file(tmp_path / "nodesign.bd", None)


# --- C1: missing required XCI parameter -> named RuntimeError, not a bare assert

def test_xci_xml_missing_device_param_raises_named_runtime_error(tmp_path):
    p = tmp_path / "my_ip.xci"
    p.write_text(_xci_xml(omit=["PROJECT_PARAM.DEVICE"]))
    with pytest.raises(RuntimeError) as ei:
        parse_x_xci_file(p, None)
    assert not isinstance(ei.value, AssertionError)
    assert str(p) in str(ei.value)
    assert "PROJECT_PARAM.DEVICE" in str(ei.value)


# --- C2: an empty <spirit:library/> must not crash with a bare AssertionError --

def test_xci_xml_empty_library_element_does_not_crash(tmp_path):
    p = tmp_path / "my_ip.xci"
    p.write_text(_xci_xml(omit_library=True))
    with pytest.raises(RuntimeError) as ei:
        parse_x_xci_file(p, None)
    assert not isinstance(ei.value, AssertionError)
    assert "library" in str(ei.value).lower()


# --- C3: coefficient scan must not abandon on a placeholder parameter ----------

def test_xci_xml_coefficient_scan_skips_placeholder_then_finds_real(tmp_path):
    (tmp_path / "real.coe").write_text("; coefficients\n")
    # placeholder (no .coe/.mif suffix) BEFORE the real one -- with the old
    # `break`-on-skip bug the scan would abandon and never see the real entry.
    extra = (
        '    <spirit:configurableElementValue spirit:referenceId="PROJECT_PARAM.COE_FILE">'
        'auto</spirit:configurableElementValue>\n'
        '    <spirit:configurableElementValue spirit:referenceId="PROJECT_PARAM.COEFFICIENT_FILE">'
        'real.coe</spirit:configurableElementValue>'
    )
    p = tmp_path / "my_ip.xci"
    p.write_text(_xci_xml(extra_elements=extra))
    sf = parse_x_xci_file(p, None)
    assert [d.name for d in sf.direct_deps] == ["real.coe"]


def test_xci_json_coefficient_scan_skips_placeholder_then_finds_real(tmp_path):
    (tmp_path / "real.coe").write_text("; coefficients\n")
    doc = {
        "ip_inst": {
            "xci_name": "my_ip",
            "parameters": {
                "project_parameters": {
                    "DEVICE": [{"value": "xc7a35t"}],
                    "PACKAGE": [{"value": "cpg236"}],
                    "SPEEDGRADE": [{"value": "-1"}],
                    "TEMPERATURE_GRADE": [{"value": "i"}],
                },
                "runtime_parameters": {"SWVERSION": [{"value": "2020.1"}]},
                # placeholder key BEFORE the real one (dict/JSON preserve order)
                "component_parameters": {
                    "Coe_File_Placeholder": [{"value": "auto"}],
                    "Coefficient_File": [{"value": "real.coe"}],
                },
            },
        }
    }
    p = tmp_path / "my_ip.xci"
    p.write_text(json.dumps(doc))
    sf = parse_x_xci_file(p, None)
    assert [d.name for d in sf.direct_deps] == ["real.coe"]


# --- C6: coefficient scan must not crash on a malformed component-parameter value


def _xci_json_doc(component_parameters):
    return {
        "ip_inst": {
            "xci_name": "my_ip",
            "parameters": {
                "project_parameters": {
                    "DEVICE": [{"value": "xc7a35t"}],
                    "PACKAGE": [{"value": "cpg236"}],
                    "SPEEDGRADE": [{"value": "-1"}],
                    "TEMPERATURE_GRADE": [{"value": "i"}],
                },
                "runtime_parameters": {"SWVERSION": [{"value": "2020.1"}]},
                "component_parameters": component_parameters,
            },
        }
    }


@pytest.mark.parametrize(
    "coef_value",
    [
        pytest.param([{"value": "a.coe"}, {"value": "b.coe"}], id="two_element_list"),
        pytest.param("a.coe", id="scalar_not_a_list"),
        pytest.param({"value": "a.coe"}, id="dict_not_a_list"),
        pytest.param([{"value": 42}], id="non_string_value"),
    ],
)
def test_xci_json_coefficient_scan_skips_malformed_value_shape(tmp_path, coef_value):
    # A JSON XCI that is otherwise perfectly valid (DEVICE/PACKAGE/SPEEDGRADE/
    # TEMPERATURE_GRADE/SWVERSION all present and well-shaped) but whose
    # COE_FILE component parameter has a shape js_val() can't handle (the old
    # code called js_val() outside the shape-guard try/except that protects
    # the required parameters, so this used to raise AssertionError / KeyError
    # / AttributeError straight out of the parser). The malformed parameter
    # must instead be skipped (logged) so the rest of the file still parses.
    p = tmp_path / "my_ip.xci"
    p.write_text(json.dumps(_xci_json_doc({"COE_FILE": coef_value})))
    sf = parse_x_xci_file(p, None)  # must not raise
    assert sf.provides == [Name("work", "my_ip")]
    assert sf.direct_deps == []  # malformed parameter contributed no dependency


@pytest.mark.parametrize(
    "component_parameters",
    [
        pytest.param([], id="list"),
        pytest.param("oops", id="string"),
        pytest.param(None, id="null"),
    ],
)
def test_xci_json_coefficient_scan_skips_non_mapping_component_parameters(tmp_path, component_parameters):
    # component_parameters itself (not just one of its values) can be
    # malformed; an otherwise-valid XCI must still parse rather than crash
    # with AttributeError from `comp_param.keys()`.
    p = tmp_path / "my_ip.xci"
    p.write_text(json.dumps(_xci_json_doc(component_parameters)))
    sf = parse_x_xci_file(p, None)  # must not raise
    assert sf.provides == [Name("work", "my_ip")]
    assert sf.direct_deps == []


# --- C4: JSON that isn't XCI-shaped falls through to a clean, file-naming error

def test_xci_json_non_xci_shaped_falls_through_to_named_runtime_error(tmp_path):
    p = tmp_path / "not_xci.xci"
    p.write_text('{"some_other_schema": {"foo": "bar"}}')
    with pytest.raises(RuntimeError) as ei:
        parse_x_xci_file(p, None)
    assert not isinstance(ei.value, (KeyError, AssertionError))
    assert str(p) in str(ei.value)


# --- C5: log-message typos fixed ------------------------------------------------

def test_xci_xml_temperature_grade_fallback_message_has_no_typos(tmp_path, capsys):
    p = tmp_path / "my_ip.xci"
    p.write_text(_xci_xml(overrides={"PROJECT_PARAM.TEMPERATURE_GRADE": ""}))
    sf = parse_x_xci_file(p, None)
    assert sf.x_device.endswith("-i")  # fell back to temperature grade 'i'
    err = capsys.readouterr().err
    assert "assuming temperature grade 'i'" in err
    assert "incorrect please report a bug" in err
    assert "assming" not in err and "temperate" not in err and "incorect" not in err


def test_xci_xml_multiple_instance_names_error_has_no_typo(tmp_path):
    xml = _xci_xml()
    xml = xml.replace(
        "</spirit:instanceName>",
        "</spirit:instanceName>\n  <spirit:instanceName>my_ip_1</spirit:instanceName>",
        1,
    )
    p = tmp_path / "my_ip.xci"
    p.write_text(xml)
    with pytest.raises(RuntimeError) as ei:
        parse_x_xci_file(p, None)
    assert "expected to find only one" in str(ei.value)
    assert "expect ton only find" not in str(ei.value)


def test_xci_declares_log_messages_have_no_typos(tmp_path, capsys, monkeypatch):
    import hdldepends.logging_util as logging_util

    monkeypatch.setattr(logging_util, "log_level", 1)  # enable log.info output

    xml_p = tmp_path / "xml_ip.xci"
    xml_p.write_text(_xci_xml())
    parse_x_xci_file(xml_p, None)
    err = capsys.readouterr().err
    assert "declares" in err and "tool_version" in err
    assert "decares" not in err and "tool_verison" not in err

    json_p = tmp_path / "json_ip.xci"
    json_p.write_text(json.dumps({
        "ip_inst": {
            "xci_name": "json_ip",
            "parameters": {
                "project_parameters": {
                    "DEVICE": [{"value": "xc7a35t"}],
                    "PACKAGE": [{"value": "cpg236"}],
                    "SPEEDGRADE": [{"value": "-1"}],
                    "TEMPERATURE_GRADE": [{"value": "i"}],
                },
                "runtime_parameters": {"SWVERSION": [{"value": "2020.1"}]},
            },
        }
    }))
    parse_x_xci_file(json_p, None)
    err = capsys.readouterr().err
    assert "declares" in err and "tool_version" in err
    assert "decares" not in err and "tool_verison" not in err


# --- tool-version comparison must be numeric, not lexicographic ----------------

def test_version_key_orders_numeric_parts_correctly():
    assert _version_key("2019.2") < _version_key("2019.10")
    assert _version_key("2019.10") > _version_key("2019.2")
    assert sorted(["2019.10", "2019.2", "2019.1"], key=_version_key) == ["2019.1", "2019.2", "2019.10"]


def test_closest_x_version_numeric_not_lexicographic():
    # "2019.10" > "2019.2" numerically, but "2019.10" < "2019.2" lexicographically
    # (the previous bug: plain string comparison).
    a = SourceFile(Path("/x/a.xci"), FileType.X_XCI, x_tool_version="2019.2", x_device="dev")
    b = SourceFile(Path("/x/b.xci"), FileType.X_XCI, x_tool_version="2019.10", x_device="dev")
    # target below both real versions -> lowest above wins; 2019.2 is the lowest.
    assert _closest_x_version([a, b], "2019.1") is a
    # target at/above both -> highest at/below wins; 2019.10 is the highest.
    assert _closest_x_version([a, b], "2020.1") is b
    assert _closest_x_version([a, b], "2019.10") is b
