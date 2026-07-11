"""Adversarial Xilinx vendor-parser probes (Stage 5.5).

Malformed/degenerate .xci/.bd inputs must fail loudly, not produce a silently
wrong file object.
"""

import json

import pytest

from hdldepends.vendors.xilinx.bd import parse_x_bd_file
from hdldepends.vendors.xilinx.xci import parse_x_xci_file


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_empty_xci_raises(tmp_path):
    # test/vhdl/delComp2.xci is a real 0-byte file; an empty .xci is neither
    # JSON nor XML and must raise rather than return a bogus object. Neither
    # sub-parser can make sense of it, so parse_x_xci_file falls through to
    # its own final RuntimeError.
    p = _write(tmp_path, "empty.xci", "")
    with pytest.raises(RuntimeError):
        parse_x_xci_file(p, None)


def test_garbage_xci_raises_runtime_error(tmp_path):
    p = _write(tmp_path, "junk.xci", "this is neither json nor xml <<<")
    with pytest.raises(RuntimeError):
        parse_x_xci_file(p, None)


def test_bd_malformed_json_raises(tmp_path):
    # .bd is JSON-only (no XML fallback); malformed JSON now raises a clean,
    # file-naming RuntimeError instead of a bare json.JSONDecodeError.
    p = _write(tmp_path, "bad.bd", "{ not valid json ")
    with pytest.raises(RuntimeError, match="bad.bd") as ei:
        parse_x_bd_file(p, None)
    assert not isinstance(ei.value, json.JSONDecodeError)


def test_bd_missing_design_key_raises(tmp_path):
    # Well-formed JSON but missing the expected "design" structure: raises a
    # RuntimeError naming the file, not a bare KeyError.
    p = _write(tmp_path, "nodesign.bd", '{"something_else": {}}')
    with pytest.raises(RuntimeError, match="nodesign.bd"):
        parse_x_bd_file(p, None)


def test_bd_top_level_not_an_object_raises_named_runtime_error(tmp_path):
    # Valid JSON but the top level is a list (or any other non-mapping):
    # subscripting it with a string key raises TypeError, which must be
    # caught alongside KeyError and turned into the same clean,
    # file-naming RuntimeError -- not a bare TypeError.
    p = _write(tmp_path, "list_top.bd", "[1, 2, 3]")
    with pytest.raises(RuntimeError, match="list_top.bd") as ei:
        parse_x_bd_file(p, None)
    assert not isinstance(ei.value, TypeError)


def test_bd_design_info_not_a_mapping_raises_named_runtime_error(tmp_path):
    p = _write(tmp_path, "bad_info.bd", '{"design": {"design_info": "oops"}}')
    with pytest.raises(RuntimeError, match="bad_info.bd") as ei:
        parse_x_bd_file(p, None)
    assert not isinstance(ei.value, TypeError)


def _bd_doc(components):
    return json.dumps({
        "design": {
            "design_info": {"tool_version": "2024.2", "device": "xcvu9p", "name": "design_1"},
            "components": components,
        }
    })


def test_bd_non_mapping_components_skipped_not_fatal(tmp_path, capsys):
    # An otherwise-valid .bd whose "components" is the wrong shape must still
    # parse (the design name is still provided) -- just with the component
    # scan skipped and a warning logged, not the whole file crashing.
    p = _write(tmp_path, "bad_components.bd", _bd_doc([1, 2, 3]))
    sf = parse_x_bd_file(p, None)
    assert [n.name for n in sf.provides] == ["design_1"]
    assert sf.requires == []
    assert "non-mapping 'components'" in capsys.readouterr().err


def test_bd_component_value_not_a_mapping_skipped_not_fatal(tmp_path):
    p = _write(tmp_path, "bad_component.bd", _bd_doc({"comp0": "not_a_dict"}))
    sf = parse_x_bd_file(p, None)
    assert sf.requires == []


def test_bd_hdl_reference_missing_ref_name_skipped_not_fatal(tmp_path):
    # Previously `ref["ref_name"]` raised a bare KeyError when absent.
    p = _write(tmp_path, "no_ref_name.bd", _bd_doc({"comp0": {"reference_info": {"ref_type": "hdl"}}}))
    sf = parse_x_bd_file(p, None)
    assert sf.requires == []


def test_bd_malformed_active_synth_bd_skipped_not_fatal(tmp_path):
    # Previously `component["parameters"]["ACTIVE_SYNTH_BD"]["value"]` raised
    # a bare TypeError when ACTIVE_SYNTH_BD wasn't a {"value": ...} mapping.
    p = _write(
        tmp_path, "bad_synth.bd",
        _bd_doc({"comp0": {"parameters": {"ACTIVE_SYNTH_BD": "not_a_dict_with_value"}}}),
    )
    sf = parse_x_bd_file(p, None)
    assert sf.requires == []


def test_xci_json_missing_required_keys_raises(tmp_path):
    # Valid JSON but not XCI-shaped: the JSON sub-parser swallows the
    # KeyError and returns None, the XML sub-parser can't parse JSON either,
    # so parse_x_xci_file falls through to its own final RuntimeError.
    p = _write(tmp_path, "partial.xci", '{"ip_inst": {"xci_name": "x"}}')
    with pytest.raises(RuntimeError):
        parse_x_xci_file(p, None)
