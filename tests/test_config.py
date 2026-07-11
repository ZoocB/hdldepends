"""Unit tests for config loading + the plain-Python validation gate."""

import json
from pathlib import Path

import pytest

from hdldepends import config as config_mod
from hdldepends.config import _find_config, load_config
from hdldepends.config_models import (
    ALL_BASE_KEYS,
    OTHER_KEYS,
    SOURCE_KEYS,
    ConfigError,
    validate_config,
)
from hdldepends.util import key_split_opt_ver, path_abs_from_dir, resolve_abs_path

# --- schema validation -----------------------------------------------------

def test_rich_valid_config_accepted():
    cfg = {
        "min_ver": 1.01,
        "sub": "other.toml",
        "ignore_libs": ["ieee", "std"],
        "ignore_components": "delComp2",
        "x_tool_version": "2024.2",
        "vhdl_files@p": {"work": ["./a.vhd", "./b.vhd"]},
        "verilog_files_glob@p": "./*.sv",
        "x_xci_files_glob": ["./*.xci", "!*skip.xci"],
        "init_files": [["enc.vhd", "VHDL"]],
        "vhdl_package_skip_order": {"unisim": "./unisim_VCOMP.vhd"},
    }
    # validate_config raises ConfigError on rejection; accepting silently
    # (returning None) is the pass signal.
    assert validate_config(cfg, "test.toml") is None


def test_unknown_key_gives_did_you_mean():
    with pytest.raises(ConfigError) as ei:
        validate_config({"vhdl_filez": "./a.vhd"}, "test.toml")
    msg = str(ei.value)
    assert "vhdl_filez" in msg and "vhdl_files" in msg


def test_tag_allowed_on_source_key_but_empty_and_double_rejected():
    validate_config({"vhdl_files@v2008": "./a.vhd"}, "t.toml")  # ok
    with pytest.raises(ConfigError):
        validate_config({"vhdl_files@": "./a.vhd"}, "t.toml")  # empty tag
    with pytest.raises(ConfigError):
        validate_config({"vhdl_files@a@b": "./a.vhd"}, "t.toml")  # double tag


# --- Stage 6 F7: an @tag on a key that doesn't take one (OTHER_KEYS) --------
# previously passed validation and was then silently ignored: gather()'s
# key_split_opt_ver / _for_each_file_spec machinery only ever looks for the
# BARE key, so e.g. `top_entity@rtl: top` never set top_entity at all, with
# no diagnostic anywhere.

def test_tag_on_other_key_rejected_with_named_message():
    with pytest.raises(ConfigError) as ei:
        validate_config({"top_entity@rtl": "top"}, "t.toml")
    assert "top_entity" in str(ei.value) and "does not take" in str(ei.value)


def test_tag_on_other_key_rejected_for_every_other_key():
    # sub / ignore_libs / x_tool_version etc. are all in OTHER_KEYS.
    for key in ("sub", "ignore_libs", "x_tool_version", "min_ver"):
        with pytest.raises(ConfigError):
            validate_config({f"{key}@tag": "x"}, "t.toml")


def test_tag_still_allowed_on_source_keys_after_f7():
    # SOURCE_KEYS (vhdl_files, ext_files, top_vhdl_file, ...) must be unaffected.
    validate_config({"vhdl_files@tag": "./a.vhd"}, "t.toml")
    validate_config({"ext_files@tag": "./a.xdc"}, "t.toml")
    validate_config({"top_vhdl_file@tag": "./a.vhd"}, "t.toml")


def test_min_ver_must_be_number():
    with pytest.raises(ConfigError):
        validate_config({"min_ver": "1.0"}, "t.toml")
    # bool is not an acceptable number even though it subclasses int
    with pytest.raises(ConfigError):
        validate_config({"min_ver": True}, "t.toml")


# --- format parity (TOML / JSON / YAML load to the same dict) ---------------

def test_three_formats_load_to_equal_dicts(tmp_path: Path):
    toml_text = 'ignore_libs = ["ieee", "std"]\n[vhdl_files]\nwork = ["./del211.vhd", "./del21.vhd"]\n'
    data = {"ignore_libs": ["ieee", "std"], "vhdl_files": {"work": ["./del211.vhd", "./del21.vhd"]}}
    yaml_text = "ignore_libs: [ieee, std]\nvhdl_files:\n  work:\n    - ./del211.vhd\n    - ./del21.vhd\n"

    (tmp_path / "c.toml").write_text(toml_text)
    (tmp_path / "c.json").write_text(json.dumps(data))
    (tmp_path / "c.yaml").write_text(yaml_text)

    loaded = [load_config(tmp_path / f"c.{ext}") for ext in ("toml", "json", "yaml")]
    assert loaded[0] == loaded[1] == loaded[2] == data
    # and all validate cleanly
    for cfg in loaded:
        validate_config(cfg, "c")


# --- sanity: the schema's key set is the union of source + other keys -------

def test_schema_key_sets_consistent():
    assert ALL_BASE_KEYS == OTHER_KEYS | SOURCE_KEYS
    # a representative key from each group
    assert "vhdl_files" in SOURCE_KEYS
    assert "ignore_libs" in OTHER_KEYS and "sub" in OTHER_KEYS


# --- F1: path_abs_from_dir env-var substitution -----------------------------

def test_path_abs_from_dir_unset_env_var_raises_named_runtime_error(tmp_path, monkeypatch):
    # str.format(**os.environ) used to raise a bare KeyError for an unset
    # {VAR}, making the "helpful" RuntimeError below it unreachable.
    monkeypatch.delenv("HDLDEPENDS_TEST_UNSET_VAR", raising=False)
    with pytest.raises(RuntimeError) as ei:
        path_abs_from_dir(tmp_path, Path("{HDLDEPENDS_TEST_UNSET_VAR}/foo.vhd"))
    assert not isinstance(ei.value, KeyError)
    assert "HDLDEPENDS_TEST_UNSET_VAR" in str(ei.value)
    assert "not set" in str(ei.value)


def test_path_abs_from_dir_set_env_var_substitutes(tmp_path, monkeypatch):
    monkeypatch.setenv("HDLDEPENDS_TEST_VAR", str(tmp_path))
    result = path_abs_from_dir(tmp_path, Path("{HDLDEPENDS_TEST_VAR}/foo.vhd"))
    assert result == (tmp_path / "foo.vhd").resolve()


# --- F2: resolve_abs_path always normalizes ---------------------------------

def test_resolve_abs_path_normalizes_dotdot_in_absolute_paths(tmp_path):
    # Previously only relative paths were resolved, so an absolute path
    # containing ".." was returned unnormalized.
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    messy = tmp_path / "a" / "b" / ".." / "b"
    assert messy.is_absolute()
    assert resolve_abs_path(messy) == nested.resolve()


# --- G1: load_config STDOUT pollution + actionable missing-lib errors ------

def test_load_config_error_goes_to_stderr_not_stdout(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    # load_config logs (to stderr) which file failed, then wraps the raw
    # json.JSONDecodeError into a clean, file-naming ConfigError -- not a
    # bare JSONDecodeError (previously re-raised as-is, uncaught anywhere
    # up to the CLI, which produced a raw traceback for the user).
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert not isinstance(ei.value, json.JSONDecodeError)
    assert str(p) in str(ei.value)
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing printed to stdout (downstream tools parse it)
    assert "failed to load config" in captured.err


def test_load_config_bad_toml_syntax_raises_config_error_not_bare_decode_error(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("this is not valid toml @@@ [[[")
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert "toml" in str(ei.value).lower()
    assert str(p) in str(ei.value)


def test_load_config_bad_yaml_syntax_raises_config_error_not_bare_decode_error(tmp_path):
    p = tmp_path / "bad.yaml"
    # unbalanced flow mapping -- a YAML scanner/parser error, not a Python one
    p.write_text("a: [1, 2\nb: {c: d\n")
    with pytest.raises(ConfigError) as ei:
        load_config(p)
    assert "yaml" in str(ei.value).lower()
    assert str(p) in str(ei.value)


def test_load_config_missing_tomllib_raises_actionable_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "tomllib", None)
    p = tmp_path / "c.toml"
    p.write_text("a = 1\n")
    with pytest.raises(RuntimeError) as ei:
        load_config(p)
    assert not isinstance(ei.value, AssertionError)
    assert "tomli" in str(ei.value).lower()


def test_load_config_missing_yaml_raises_actionable_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "yaml", None)
    p = tmp_path / "c.yaml"
    p.write_text("a: 1\n")
    with pytest.raises(RuntimeError) as ei:
        load_config(p)
    assert not isinstance(ei.value, AssertionError)
    assert "pyyaml" in str(ei.value).lower()


# --- G2: ConfigError replaces bare Exception --------------------------------

def test_find_config_bad_suffix_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        _find_config(tmp_path / "cfg.txt", None)


def test_key_split_opt_ver_too_many_tags_raises_config_error():
    with pytest.raises(ConfigError) as ei:
        key_split_opt_ver("a@b@c")
    # the exception IS the error -- no redundant "ERROR:" prefix in the message
    assert not str(ei.value).startswith("ERROR:")
