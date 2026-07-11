"""Adversarial config-loader probes (build_resolver + the plain-Python validation gate)."""

from pathlib import Path

import pytest

from hdldepends.config import build_resolver
from hdldepends.config_models import ConfigError, validate_config


def _build(tmp_path, monkeypatch, name="hdldeps.toml"):
    monkeypatch.chdir(tmp_path)
    return build_resolver(name, work_dir=Path("."))


def test_empty_config_builds_without_error(tmp_path, monkeypatch):
    (tmp_path / "hdldeps.toml").write_text("")
    assert _build(tmp_path, monkeypatch) is not None


def test_min_ver_too_high_raises(tmp_path, monkeypatch):
    # G2: bare Exception -> ConfigError (same message).
    (tmp_path / "hdldeps.toml").write_text("min_ver = 9999.0\n")
    with pytest.raises(ConfigError):
        _build(tmp_path, monkeypatch)


def test_glob_matching_nothing_is_ok(tmp_path, monkeypatch):
    (tmp_path / "hdldeps.toml").write_text("vhdl_files_glob = './does_not_exist_*.vhd'\n")
    assert _build(tmp_path, monkeypatch) is not None


def test_glob_pattern_matching_a_directory_does_not_crash(tmp_path, monkeypatch):
    # Stage 6 F6: a glob like 'src/**' matches directories as well as files
    # (with recursive=True, `**` matches the 'src' dir itself and every
    # subdirectory under it, not just files) -- a directory reaching the
    # parsers previously raised a raw IsADirectoryError. Only files should
    # survive process_glob_patterns' inclusion matching; the directory itself
    # (and any subdirectory) must be silently skipped.
    src_dir = tmp_path / "src"
    sub_dir = src_dir / "subdir"
    sub_dir.mkdir(parents=True)
    (src_dir / "a.vhd").write_text("library ieee;\nentity a is end entity;\n")
    (sub_dir / "b.vhd").write_text("library ieee;\nentity b is end entity;\n")
    (tmp_path / "hdldeps.toml").write_text('vhdl_files_glob = ["src/**"]\n')
    r = _build(tmp_path, monkeypatch)
    stems = {p.stem for p in r.by_loc}
    assert {"a", "b"} <= stems


def test_immediate_self_referencing_sub_raises(tmp_path, monkeypatch):
    # G2: bare Exception -> ConfigError (same message).
    (tmp_path / "hdldeps.toml").write_text("sub = 'hdldeps.toml'\n")
    with pytest.raises(ConfigError):
        _build(tmp_path, monkeypatch)


def test_transitive_circular_sub_gives_clean_error(tmp_path, monkeypatch):
    # G2: bare Exception -> ConfigError (same message).
    (tmp_path / "a.toml").write_text("sub = 'b.toml'\n")
    (tmp_path / "b.toml").write_text("sub = 'a.toml'\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        build_resolver("a.toml", work_dir=Path("."))
    assert not isinstance(ei.value, RecursionError)
    assert "circular" in str(ei.value).lower()


def test_diamond_sub_configs_allowed(tmp_path, monkeypatch):
    (tmp_path / "shared.toml").write_text("ignore_libs = ['ieee']\n")
    (tmp_path / "l.toml").write_text("sub = 'shared.toml'\n")
    (tmp_path / "r.toml").write_text("sub = 'shared.toml'\n")
    (tmp_path / "top.toml").write_text("sub = ['l.toml', 'r.toml']\n")
    monkeypatch.chdir(tmp_path)
    assert build_resolver("top.toml", work_dir=Path(".")) is not None


def test_unknown_key_gives_did_you_mean():
    with pytest.raises(ConfigError) as ei:
        validate_config({"vhdl_filez": "./a.vhd"}, "t.toml")
    assert "vhdl_filez" in str(ei.value) and "vhdl_files" in str(ei.value)


def test_min_ver_wrong_type_is_rejected_by_schema():
    with pytest.raises(ConfigError):
        validate_config({"min_ver": "not a number"}, "t.toml")
